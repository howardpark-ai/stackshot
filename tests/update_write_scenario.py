"""Scenario test for the update, complete and confirm writes (stackshot/service/update.py: `update_item`, `update_unlocked`, `complete_item`, `confirm_item` with their `Hooks`) — a scratch store, fake hooks, no server, no port, no network.

The update runs the write gates (service/gates.py: this suite replaces each there with a recorder) and the checks and notices that are still server.py's through `Hooks`, saves through the write path (`service/writes.py`) and tells the sessions the write concerns, in an order that is part of what an
update means. This suite installs hooks that record each call and return what a gate that lets the write through returns, wraps the save in a recorder (which calls the real one) and holds:

  1  order          the whole sequence of a plain update, from the pre-lock read of an event wait to the publish; the save comes before the publish, the gates before the save
  2  flags          the thread-local flags are read through the hooks, on writes that reach each gate: a session's write meets the front-step and clock-renewal gates (with the flag on, never off; a script's write, a write with the model's guards off and a re-bullet do not), the owner-step gate follows a write of next (the terminal prompt's row is exempt), a re-bullet owes the page nothing
  3  context        the write context the save gets: a bookkeeping write and a re-bullet are quiet, a write that names the mover is named, any other is plain; the writer is the sender or the item's mover
  4  lock           the item lock is held across the save and released after, also when the update refuses; the event wait's facts are read before the lock
  5  close flag      a close sets the close flag with the item as it stood, and the entry clears it afterwards, also when the update refuses
  6  refusals        a gate that refuses stops the update before anything is written; an unknown item is refused
  7  complete        the complete write makes the update with status=completed through the hook the server fills, then appends the anchors prompt (a failing prompt is told, not raised)
  8  confirm         a confirm moves the `confirmed` clock only, saves quietly under the confirm activity, publishes and appends the nag; its writer is the sender or the item's mover; its reply tells the time in the zone the server holds
  9  the helpers     the private helpers that moved with the write, called directly: the retired-input note, the hand-off line test, the stale-next mark, the hand-off list, the contact after a move, the doing note, the loose wait reason, the time-wait reading, each on a non-default input and an edge, expected values taken from main's own functions
  10 the table       the table the server builds holds every hook and looks each up when it is called (a patch of the server's name, or of the nag's owner, after the install reaches the update); every `_late("<name>")` target of its two tables is a name of the server; the zone is the server's own;
                     a write with no hooks installed is refused
 11  the layers      service/update.py imports nothing from web/, and web/server.py defines none of the moved bodies (the three tools, in web/tools/, are thin wrappers)

    tests/run-suite update_write        -> exit 0 / 1"""
import ast, dataclasses, datetime, json, os, pathlib, re, sys, threading, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
sys.path.insert(0, STACK); sys.path.insert(0, os.path.join(STACK, "tools"))
tmp = _scratch.mkdtemp(prefix="upd3-update-write-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "home").mkdir(); (T / "store/a").mkdir(parents=True); (T / "store/g").mkdir(parents=True); (T / "store/s").mkdir(parents=True); (T / "fleet").mkdir(); (T / "state").mkdir()
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", HOME=str(T / "home"), STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:1200]}" if got is not None else ""))

from fastmcp.exceptions import ToolError
from stackshot.core import store as cstore
from stackshot.service import gates, telling, update, writes
cstore.STORE = T / "store"

LOG = []                                                     # every hook and the save, in the order they were called: (name, args, kwargs)
class _Flags(dict):
    """The per-write flags the update reads, which are service/writes.py's thread-locals now: `FLAGS.update(session_next=True)` turns one on there."""
    def update(self, **kw):
        for k, v in kw.items(): getattr(writes, k.upper()).on = bool(v)
        super().update(**kw)
FLAGS = _Flags(session_next=False, reformat=False, terminal_row=False, question=False)
RET = {}                                                     # a hook's return value by name, where the default below is not what a case needs
RAISE = {}                                                   # a hook that refuses (ToolError) by name
SEEN = {}                                                    # what a hook saw when it ran (the lock, a thread's view)
BORED = {"ask_owed": "", "gate_options": None, "gate_needs": [], "gate_observers": [], "gate_after": [], "gate_said": [], "gate_state_args": ("", {}, False), "gate_draft_args": ("", False),
         "gate_model_args": ({}, {}), "gate_close": "", "contact_alive": True, "date_parked": False, "is_held": False, "marks_given": False, "name_on_write": None,
         "fmt": "<item>", "nag": "", "holder": "wr3-mover", "session_id": None, "model_guards_on": True, "form_notes": "", "machine_note": "", "watch_on_write": "", "release_after": "",
         "quiet": "", "main_agent": "", "page_keeper": "", "pilot_charge": ("", ""), "writer_owes": False, "pilot_relay": "", "tell_needed": "", "handoff_notify": "", "tell_owner": "",
         "tell_owner_change": "", "tell_owner_close": "", "tell_observers": "", "tell_decided": "", "tell_handback": "", "mentions_reply": "", "owner_then_default": "", "options_note": "",
         "actor_note": "", "wake_window_note": "", "wake_step_note": "", "wake_park_line": "", "render_when_words": "", "render_hold_at": "", "render_option_lines": "", "render_same_ref": False,
         "owner_want": "", "owner_state_mover": "", "owner_reached": False, "owner_quote_on": ("", "", ""), "state_apply": "", "state_end": None, "model_apply": None, "model_of": {},
         "switchover_on": False, "eff_state": "", "ho_derive": "", "ho_same": False, "hold_held_by": "", "hold_set": None, "handoffs_in": [], "session_roster": [], "scoped_anchors": [],
         "said_note": "", "parse_check": "", "parse_wake": None, "wake_at": None, "wake_event_set": None, "wait_end_sent_back": None, "store_ref": "", "step_proof_set": "",
         "step_proof_prune": "", "record_fixes": None, "front_sender": False, "contact_fronts": [], "contact_same": False, "fallback_wait_date": ("", "", ""), "date_only_wait": False,
         "basis_put": None, "basis_words": "", "cap_ok_put": None, "cap_ok_drop": None, "check_how": "", "nl_text_without": "", "finishes_own_line": False, "require_marks": None,
         "owed_mark": None, "refuse_if_owing": None, "push_noted": None, "writer_charge": "", "owner_state_mover_": "", "evwait_preread": None, "close_was_set": None, "lift_ask": "",
         "gate_repark": None, "gate_clock_renewal": None, "gate_ask_on_wait": None, "handover": "", "handoffs_in_": [], "anchor_wait_gate": None, "after_open": False, "gate_work_writer": None}
def hook(name):
    def run(*a, **k):
        LOG.append((name, a, k))
        if name in RAISE: raise ToolError(RAISE[name])
        if name in RET: return RET[name]
        if name == "session_id": return a[0] if a else ""
        if name == "gate_ask": return a[0]
        if name == "gate_model_args": return ({}, {})
        if name == "name_on_write": return lambda: ""
        if name == "nl_text_without": return str(a[0].get("next") or "")           # the lines of next the write leaves, as the server reads them out of the stored next
        if name == "marks_given": return bool(a[0]) if a else False
        return BORED.get(name, "")
    return run
def flag(name):
    def run():
        LOG.append((name, (), {}))
        return FLAGS[name]
    return run
# the write gates are service/gates.py's, not hooks: the update calls them on that module, so this suite replaces each there (the recorder above) and puts the real ones back before it imports the server
REAL_GATES = {n: getattr(gates, n) for n in dir(gates) if n.startswith("gate_") and callable(getattr(gates, n))}
for _n in REAL_GATES: setattr(gates, _n, hook(_n))
# the telling is service/telling.py's, not a hook either: the update calls each notice on that module, so this suite replaces the ones it calls there with the same recorder (logged under the name the hook had)
REAL_TELLING = {n: getattr(telling, n) for n in ("front_sender", "handoff_notify", "holder", "mentions_reply", "owner_reached", "page_keeper", "pilot_charge", "pilot_relay", "push_noted", "quiet_line",
                                                 "tell_decided", "tell_handback", "tell_needed", "tell_observers", "tell_owner", "tell_owner_change", "tell_owner_close", "writer_charge")}
for _n in REAL_TELLING: setattr(telling, _n, hook("quiet" if _n == "quiet_line" else _n))
_rec_owner = telling.tell_owner
def _tell_owner_seen(*a, **k):
    SEEN["close_was_in_tell"] = getattr(telling.CLOSE_WAS, "item", None)      # what the close flag held when the mover was told
    return _rec_owner(*a, **k)
telling.tell_owner = _tell_owner_seen
def make_hooks(**over):
    kw = {}
    for f in dataclasses.fields(update.Hooks):
        if f.name in FLAGS: kw[f.name] = flag(f.name)
        elif f.name == "ask_none": kw[f.name] = ("none", "clear", "-")
        elif f.name == "zone": kw[f.name] = lambda: datetime.timezone.utc
        else: kw[f.name] = hook(f.name)
    kw.update(over)
    return update.Hooks(**kw)

STEPS = ("settle_mover", "owner_steps", "ask_stamp", "handoff_on_save", "handoff_his_over", "handoff_follow", "phase_stamp", "foryou_on_save", "landed_on_save", "search_touch", "handback_drop", "answer_ack")
writes.install(writes.Steps(**{n: (lambda *a, **k: None) for n in STEPS}))
real_save = writes.save
def save(gid, item, **kw):
    LOG.append(("save", (gid,), dict(kw, subject=item.get("subject"), description=item.get("description"))))
    SEEN["lock_in_save"] = writes.ITEM_LOCK._is_owned()
    return real_save(gid, item, **kw)
writes.save = save

OWNER = "wr3-session"
MOVER = "wr3-mover"
def put(n, status="open", letter="a", **meta):
    """An item file as a write leaves it: open, with a goal, the creator and one step of the mover's."""
    now = time.time() - 3600
    it = {"id": str(n), "subject": "[home] an item", "description": "- Goal: Done when it is done\n- A second bullet", "status": status, "created": now, "updated": now, "state_updated": now, "confirmed": now,
          "metadata": {"owner": OWNER, "project": "projects/alpha", "next": f"{MOVER}: begin", "mover": MOVER, "goal": "Done when it is done", **meta}, "history": []}
    (T / "store" / letter / f"{n}.json").write_text(json.dumps(it), encoding="utf-8")
    return f"{letter}{n}"
def rd(gid): return json.loads((T / "store" / gid[0] / f"{gid[1:]}.json").read_text(encoding="utf-8"))
def names(skip=()):
    return [n for n, _a, _k in LOG if n not in skip]
def called(name): return [(a, k) for n, a, k in LOG if n == name]
FLAG_READS = tuple(FLAGS)
def upd(gid, **kw):
    LOG.clear()
    return update.update_item(gid, **kw)

update.install(make_hooks())

# ---------------------------------------------------------------- 1. order
g1 = put(1)
out = upd(g1, subject="[home] a renamed item", sender=OWNER)
n1 = names(skip=FLAG_READS)
check("1 a plain update returns the item as the formatter showed it, under the reply's first line", out.startswith("updated ") and "<item>" in out, out)
check("1 the event wait's facts are read first, before anything else is called", n1[0] == "evwait_preread", n1[:3])
check("1 the save comes before the publish and the publish before the end of the write", "save" in n1 and "publish" in n1 and n1.index("save") < n1.index("publish"), n1)
check("1 the model's arguments are gated before the item is written", n1.index("gate_model_args") < n1.index("save") and n1.index("gate_state_args") < n1.index("save"), n1)
check("1 the item is on disk with the new subject, and the save names the sender as the writer", rd(g1)["subject"] == "[home] a renamed item" and called("save")[0][1]["writer"] == OWNER, (rd(g1)["subject"], called("save")))
check("1 the nag is asked for, for the writer, once the item is saved", "nag" in n1 and n1.index("save") < n1.index("nag"), n1)
RET["nag"] = "\n[nag] owed"
out_n = upd(g1, subject="[home] a renamed item again", sender=OWNER)
check("1 …and the nag the hook gives is the end of the reply", out_n.endswith("\n[nag] owed"), out_n[-80:])
RET.pop("nag")
g1b = put(2)
LOG.clear()
try: update.update_item(g1b, description="- Goal: Done when it is done\n- Another bullet", sender=OWNER); desc_ok = True
except Exception as e: desc_ok = repr(e)
check("1 a description write goes through the description path, with the state change counted", desc_ok is True and rd(g1b)["description"].endswith("Another bullet"), desc_ok)

# ---------------------------------------------------------------- 2. flags
g2 = put(3)
def judged(session, n, *, put_kw=None, **kw):
    """The gates a write meets, with the session flag at `session`: the names called and the item written."""
    FLAGS.update(session_next=session); g = put(n, **(put_kw or {}))
    try: upd(g, **kw)
    finally: FLAGS.update(session_next=False)
    return names(), g
STEP = f"{MOVER}: a new second step"
on, g2n = judged(True, 31, next=STEP, sender=OWNER)
fs = called("gate_front_step")
check("2 a session's write of next reaches the front-step gate once, with the item, the steps it leaves and the sender", len(fs) == 1 and fs[0][0][0] == g2n and isinstance(fs[0][0][3], list) and fs[0][0][3] and fs[0][0][4] == OWNER, fs)
check("2 …and the clock-renewal gate and the owner-step gate", "gate_clock_renewal" in on and "gate_owner_step" in on, [n for n in on if n.startswith("gate")])
off, _g = judged(False, 32, next=STEP, sender=OWNER)
check("2 the same write that is no session's runs neither the front-step gate nor the clock-renewal gate (both are a session's checks)", "gate_front_step" not in off and "gate_clock_renewal" not in off, [n for n in off if n.startswith("gate")])
check("2 …but the owner-step gate follows the write of next, a session's or not", "gate_owner_step" in off, [n for n in off if n.startswith("gate")])
desc_on, _g = judged(True, 33, description="- Goal: Done when it is done\n- Changed by a session", sender=OWNER)
check("2 a session's write that leaves next alone reaches no front-step gate (no checklist is written) and no owner-step gate (nothing it reads changed)", "gate_front_step" not in desc_on and "gate_owner_step" not in desc_on, [n for n in desc_on if n.startswith("gate")])
check("2 …and the flag (service/writes.py's) is off again after the write", writes.SESSION_NEXT.on is False, writes.SESSION_NEXT.on)
scr_on, _g = judged(True, 34, next=STEP, sender="a script on a box")
check("2 a script's write is no write of a session even with the flag on: no front-step gate", "gate_front_step" not in scr_on, [n for n in scr_on if n.startswith("gate")])
RET["model_guards_on"] = False
nog, _g = judged(True, 35, next=STEP, sender=OWNER)
RET.pop("model_guards_on")
check("2 with the model's guards off a session's write meets neither the front-step gate nor the clock-renewal gate", "gate_front_step" not in nog and "gate_clock_renewal" not in nog, [n for n in nog if n.startswith("gate")])
FLAGS.update(terminal_row=True)
trm, _g = judged(False, 36, next=STEP, sender=OWNER)
FLAGS.update(terminal_row=False)
check("2 the terminal prompt's repair write is exempt from the owner-step gate", "gate_owner_step" not in trm, [n for n in trm if n.startswith("gate")])
FLAGS.update(reformat=True)
ref_on, _g = judged(True, 37, next=STEP, sender=OWNER)
FLAGS.update(reformat=False)
check("2 a re-bullet is exempt from the front-step gate and the clock-renewal gate", "gate_front_step" not in ref_on and "gate_clock_renewal" not in ref_on, [n for n in ref_on if n.startswith("gate")])
FLAGS.update(session_next=False)
upd(g2, description="- Goal: Done when it is done\n- Changed by a script", sender=OWNER)
check("2 a description write that is no session's runs none of the session-only gates", "gate_front_step" not in names() and "gate_clock_renewal" not in names(), [n for n in names() if n.startswith("gate")])
FLAGS.update(reformat=True)
upd(g2, description="- Goal: Done when it is done\n- Changed by a script", sender=OWNER)
check("2 a re-bullet of the description is saved as a filing edit when the flag (service/writes.py's) is on", called("save")[0][1].get("ctx") is writes.QUIET, called("save")[0][1])
FLAGS.update(reformat=False)
g2r = put(13)
RET["pilot_charge"] = ("stew-session", "name")
upd(g2r, description="- Goal: Done when it is done\n- A real change of the description", sender=OWNER)
check("2 a real change of the description owes the page: the keeper is asked who is charged", called("pilot_charge") and rd(g2r)["state_updated"] > time.time() - 60, names())
FLAGS.update(reformat=True)
g2s = put(14); was_su = rd(g2s)["state_updated"]
upd(g2s, description="- Goal: Done when it is done\n- Only re-bulleted", sender=OWNER)
check("2 …and a re-bullet owes none and leaves the state clock where it was (a re-bullet changes the form of the text, never what it says)", not called("pilot_charge") and rd(g2s)["state_updated"] == was_su, (names(), rd(g2s)["state_updated"], was_su))
RET.pop("pilot_charge")
FLAGS.update(reformat=False)
FLAGS.update(terminal_row=True)
FLAGS.update(session_next=False)
g2b = put(4)
upd(g2b, description="- Goal: Done when it is done\n- A terminal prompt's row", sender=OWNER)
n2b = names()
check("2 the terminal prompt's row owes the page nothing: no debt is marked and no keeper is told", "owed_mark" not in n2b and "pilot_relay" not in n2b, n2b)
FLAGS.update(terminal_row=False)
g2c = put(5)
RET["pilot_charge"] = ("stew-session", "name")
upd(g2c, description="- Goal: Done when it is done\n- A write of a session", sender=OWNER)
check("2 …and without the flag the same write charges the page", "owed_mark" in names() or "writer_charge" in names() or "pilot_relay" in names(), names())
RET.pop("pilot_charge")

# ---------------------------------------------------------------- 3. context
g3 = put(6)
upd(g3, description="- Goal: Done when it is done\n- Plain", sender=OWNER)
check("3 a write of the description is a plain write (the mover is flipped by the server's rules)", called("save")[0][1]["ctx"] is writes.PLAIN, called("save"))
upd(g3, subject="[home] a bookkeeping rename", sender=OWNER)
check("3 a write that only files (a rename) is quiet: no mover is settled for it", called("save")[0][1]["ctx"] is writes.QUIET, called("save"))
upd(g3, priority="p2", sender=OWNER)
check("3 …so is a priority alone", called("save")[0][1]["ctx"] is writes.QUIET, called("save"))
FLAGS.update(reformat=True)
upd(g3, description="- Goal: Done when it is done\n- Plain", sender=OWNER)
check("3 a re-bullet is quiet as well", called("save")[0][1]["ctx"] is writes.QUIET, called("save"))
FLAGS.update(reformat=False)
RET["gate_model_args"] = ({"mover": MOVER}, {})
upd(g3, mover=MOVER, description="- Goal: Done when it is done\n- Named", sender=OWNER)
check("3 a write that names the mover and does other work leaves the mover alone: the named context", called("save")[0][1]["ctx"] is writes.NAMED, called("save"))
RET.pop("gate_model_args")
upd(g3, description="- Goal: Done when it is done\n- Plain again")
check("3 a write with no sender is written by the item's mover (the holder hook), by rule", called("save")[0][1]["writer"] == MOVER and called("holder"), called("save"))

# ---------------------------------------------------------------- 4. lock
g4 = put(7)
SEEN.clear()
upd(g4, subject="[home] under the lock", sender=OWNER)
check("4 the save runs under the item lock", SEEN.get("lock_in_save") is True, SEEN)
free = []
t = threading.Thread(target=lambda: free.append(writes.ITEM_LOCK.acquire(blocking=False) and (writes.ITEM_LOCK.release() or True))); t.start(); t.join()
check("4 …and the lock is released when the write returns", free == [True], free)
def pre(kind, event):
    LOG.append(("evwait_preread", (kind, event), {}))
    SEEN["lock_in_preread"] = writes.ITEM_LOCK._is_owned()
update.install(make_hooks(evwait_preread=pre))
SEEN.clear()
upd(g4, subject="[home] an event wait", sender=OWNER, wait_kind="event", wait_event="pr_merged o/r#12")
check("4 an event wait's facts are read before the lock is taken, with the kind and the event the call passes", SEEN.get("lock_in_preread") is False and called("evwait_preread")[0][0] == ("event", "pr_merged o/r#12"), (SEEN, called("evwait_preread")))
update.install(make_hooks())
RAISE["gate_subject"] = "Refused: gate_subject"; RAISE["gate_model_args"] = "Refused: gate_model_args"
try: upd(g4, subject="[home] refused", sender=OWNER); refused = None
except ToolError as e: refused = str(e)
RAISE.pop("gate_subject"); RAISE.pop("gate_model_args")
free2 = []
t = threading.Thread(target=lambda: free2.append(writes.ITEM_LOCK.acquire(blocking=False) and (writes.ITEM_LOCK.release() or True))); t.start(); t.join()
check("4 an update that refuses leaves the lock free", refused is not None and free2 == [True], (refused, free2))

# ---------------------------------------------------------------- 5. close flag
g5 = put(8)
RET["gate_close"] = ""
SETS = []
update.install(make_hooks())
telling.CLOSE_WAS.item = None
try: upd(g5, status="completed", outcome="done", reason="it is done", outcome_text="- done", sender=OWNER); closed = True
except ToolError as e: closed = str(e)
sets = [SEEN.get("close_was_in_tell"), getattr(telling.CLOSE_WAS, "item", 1)]
check("5 a close hands the item as it stood to the close flag (service/telling.py's) while the mover is told, and the entry clears it after the write", closed is True and isinstance(sets[0], dict) and sets[0].get("status") == "open" and sets[1] is None, (closed, sets))
check("5 the item is closed on disk", rd(g5)["status"] == "completed", rd(g5).get("status"))
g5b = put(9)
SETS.clear(); LOG.clear()
RAISE["gate_subject"] = "Refused: x"
try: update.update_item(g5b, subject="[home] x", sender=OWNER)
except ToolError: pass
RAISE.pop("gate_subject")
check("5 an update that refuses clears the flag too", getattr(telling.CLOSE_WAS, "item", 1) is None, getattr(telling.CLOSE_WAS, "item", 1))
update.install(make_hooks())

# ---------------------------------------------------------------- 6. refusals
g6 = put(10)
before = rd(g6)
for hook_name in ("gate_subject", "gate_description", "gate_next", "gate_model_args", "gate_state_args", "gate_ask"):
    RAISE[hook_name] = f"Refused: {hook_name}"
    LOG.clear()
    try:
        update.update_item(g6, subject="[home] a refusal", description="- Goal: Done when it is done\n- other", next=f"{MOVER}: other", ask="why", sender=OWNER); out = None
    except ToolError as e: out = str(e)
    RAISE.pop(hook_name)
    check(f"6 a refusal by {hook_name} reaches the caller as it is", out == f"Refused: {hook_name}", out)
    check(f"6 …and writes nothing", rd(g6) == before and "save" not in names(), names())
try: upd("a99999", subject="[home] nothing", sender=OWNER); unknown = None
except ToolError as e: unknown = str(e)
check("6 an item that does not exist is refused, and nothing is saved", unknown is not None and "save" not in names(), (unknown, names()))
RAISE["gate_close"] = "Refused: gate_close"
try: upd(g6, status="completed", outcome="done", reason="r", outcome_text="- x", sender=OWNER); noclose = None
except ToolError as e: noclose = str(e)
RAISE.pop("gate_close")
check("6 a close the close gate refuses leaves the item open and unsaved", noclose == "Refused: gate_close" and rd(g6) == before and "save" not in names(), (noclose, names()))

# ---------------------------------------------------------------- 7. complete
g7 = put(11)
ANCH = []
real_prompt = update._completion_anchor_prompt
UPDATES = []
def fake_update(item_id, **kw):
    UPDATES.append((item_id, kw)); LOG.append(("update", (item_id,), kw))
    stored = rd(item_id); stored["status"] = "completed"          # what the real update does to the item: the close is on disk when the hook returns
    (T / "store" / item_id[0] / f"{item_id[1:]}.json").write_text(json.dumps(stored), encoding="utf-8")
    return "updated by the hook.\n"
update.install(make_hooks(update=fake_update))
update._completion_anchor_prompt = lambda gid, item: f"\n[anchors] prompt for {gid} ({item.get('status')})"
LOG.clear()
out_c = update.complete_item(g7, outcome="done", reason="it is done", description="", superseded_by="", sender=OWNER, said=None, outcome_text="- done")
check("7 the complete makes the update through the hook, with status=completed and the fields it was given, the description empty", UPDATES and UPDATES[0][0] == g7 and UPDATES[0][1].get("status") == "completed" and UPDATES[0][1].get("outcome") == "done" and UPDATES[0][1].get("reason") == "it is done"
      and UPDATES[0][1].get("outcome_text") == "- done" and UPDATES[0][1].get("sender") == OWNER and UPDATES[0][1].get("description") == "", UPDATES)
check("7 …the close is on disk when the hook returns (so the check below reads a different item if the prompt's item were read after the update)", rd(g7)["status"] == "completed", rd(g7).get("status"))
check("7 …and the anchors prompt is appended to the reply, read from the item as it stood before the close", out_c == f"updated by the hook.\n\n[anchors] prompt for {g7} (open)", out_c)
update._completion_anchor_prompt = lambda gid, item: (_ for _ in ()).throw(RuntimeError("prompt broke"))
try: out_c2 = update.complete_item(g7, outcome="done", reason="r", sender=OWNER)
except Exception as e: out_c2 = f"raised {e!r}"
check("7 a prompt that fails never fails the close: it is told in the reply", out_c2.endswith("\n[anchors] prompt failed: prompt broke") and out_c2.startswith("updated by the hook."), out_c2)
update._completion_anchor_prompt = real_prompt
UPDATES.clear()
update.complete_item(g7, sender=OWNER)
check("7 a complete from a pane with an older tool list (no fields) still makes the update, so its refusal says what is missing", UPDATES and UPDATES[0][1].get("outcome") == "" and UPDATES[0][1].get("status") == "completed", UPDATES)
try: update.complete_item("a99999", sender=OWNER); nf = None
except ToolError as e: nf = str(e)
check("7 a complete of an item that does not exist is refused before the update is made", nf is not None and not UPDATES[1:], (nf, UPDATES))
update.install(make_hooks())

# ---------------------------------------------------------------- 8. confirm
g8 = put(12)
was = rd(g8)
t_c = time.time()
LOG.clear()
out_f = update.confirm_item(g8, OWNER)
it8 = rd(g8)
sv8 = called("save")
check("8 a confirm moves the confirmed clock and no other clock", it8["confirmed"] >= t_c - 1 and it8["updated"] == was["updated"] and it8["state_updated"] == was["state_updated"], (it8, was))
check("8 it saves quietly under the confirm activity, written by the sender", len(sv8) == 1 and sv8[0][1]["ctx"] is writes.QUIET and sv8[0][1]["activity"] == update._activity.CONFIRM and sv8[0][1]["writer"] == OWNER, sv8)
check("8 it publishes after the save, and the reply says the item is confirmed, with the formatter's text and the nag", "publish" in names() and "save" in names() and names().index("save") < names().index("publish") and out_f.startswith("confirmed ") and "<item>" in out_f, (names(), out_f))
LOG.clear()
update.confirm_item(g8)
check("8 a confirm with no sender is written by the item's mover (the holder hook)", called("save")[0][1]["writer"] == MOVER and called("holder"), called("save"))
RET["nag"] = "\n[nag] x"
check("8 the nag is asked for the sender", update.confirm_item(g8, OWNER).endswith("\n[nag] x") and called("nag")[-1][0] == (OWNER,), called("nag"))
RET.pop("nag")
try: update.confirm_item("a99999", OWNER); nf2 = None
except ToolError as e: nf2 = str(e)
check("8 a confirm of an item that does not exist is refused", nf2 is not None, nf2)
KST = datetime.timezone(datetime.timedelta(hours=9))
update.install(make_hooks(zone=lambda: KST, render_when_words=lambda d: d.isoformat(timespec="minutes")))
out_z = update.confirm_item(g8, OWNER)
want_z = datetime.datetime.fromtimestamp(rd(g8)["confirmed"], KST).isoformat(timespec="minutes")
check("8 the reply says when it was confirmed in the zone the zone hook gives (the board's zone as the server holds it, never the config's zone read again)", want_z.endswith("+09:00") and out_z.startswith(f"confirmed {update._gh.shown(g8)} at {want_z}.\n"), out_z[:120])
update.install(make_hooks())
g8g = put(12, letter="g")
check("8 a bare number is read as the item's number (board#N)", update.confirm_item("12", OWNER).startswith("confirmed ") and rd(g8g)["confirmed"] > was["confirmed"], None)

# ---------------------------------------------------------------- 9. the helpers that moved with the write
check("9 the retired-input note is said for expected_by or expected_reason and for nothing else", update._retired_note("", None) == "" and update._retired_note("2030-01-01") == update.RETIRED_NOTE and update._retired_note("", "why") == update.RETIRED_NOTE, None)
check("9 a write is bookkeeping when every argument it passes files the item", {"project", "subject", "priority"} <= update._FILING_ONLY and "description" not in update._FILING_ONLY and "next" not in update._FILING_ONLY, sorted(update._FILING_ONLY))
update.install(make_hooks(handoffs_in=lambda text, roster: [l.split(":", 1)[0] for l in text.splitlines() if ":" in l], session_roster=lambda: []))
check("9 a line of next that starts with the session's name is a hand-off line, any other is not", update._next_names_session(f"{MOVER}: begin", MOVER) and not update._next_names_session(f"{MOVER}: begin", "other") and not update._next_names_session("", MOVER), None)
update.install(make_hooks())
check("9 an item waiting on nothing has no wait notes", update._stale_wait_notes({"metadata": {}}, {"metadata": {}}) == "", update._stale_wait_notes({"metadata": {}}, {"metadata": {}}))

# ---------------------------------------------------------------- 10. the table the server builds
update.install(None)
try: update.update_item(g1, subject="[home] x"); bare = None
except RuntimeError as e: bare = str(e)
except Exception as e: bare = f"not the install's refusal: {e!r}"
check("10 an update with no hooks installed is refused, naming the install", bare is not None and "no hooks installed" in bare, bare)
try: update.confirm_item(g1, OWNER); bare2 = None
except RuntimeError as e: bare2 = str(e)
check("10 …a confirm too", bare2 is not None and "no hooks installed" in bare2, bare2)
try: update.Hooks(**{f.name: None for f in dataclasses.fields(update.Hooks)[:-1]}); short = None
except TypeError as e: short = str(e)
check("10 a hook table with a hook missing cannot be built", short is not None, short)
for _n, _f in REAL_GATES.items(): setattr(gates, _n, _f)      # the real write gates back, as the server imports them
for _n, _f in REAL_TELLING.items(): setattr(telling, _n, _f)      # and the real notices
from stackshot.web import server, page_debts
from stackshot.web.tools import text as _wt_text
tbl = update._hooks()
check("10 no write gate is a hook of the update: the update calls each on service/gates.py, where a suite patches it", not ({f.name for f in dataclasses.fields(update.Hooks)} & set(REAL_GATES)) and len(REAL_GATES) >= 25, sorted(REAL_GATES))
srv_tree = ast.parse(pathlib.Path(STACK, "stackshot/web/server.py").read_text(encoding="utf-8"))
LATE = {}                                                    # the names the server's two tables look up late: table -> [name, ...]
for node in ast.walk(srv_tree):
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "Hooks" and isinstance(node.func.value, ast.Name) and node.func.value.id in ("_create_svc", "_update_svc"):
        LATE[node.func.value.id] = [c.args[0].value for c in ast.walk(node) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == "_late" and c.args and isinstance(c.args[0], ast.Constant)]
missing = {t: [n for n in names_ if not hasattr(server, n)] for t, names_ in LATE.items()}
check("10 every name the server's create table and update table look up late (`_late(\"<name>\")`) is an attribute of the server module (a renamed gate would otherwise fail only when a write reaches it)",
      set(LATE) == {"_create_svc", "_update_svc"} and len(LATE.get("_create_svc", ())) >= 40 and len(LATE.get("_update_svc", ())) >= 72 and not any(missing.values()), ({t: len(v) for t, v in LATE.items()}, missing))
# the helpers that moved with the write, called directly on inputs where each differs from its default and on an edge, through the table the server builds. The expected values are what main's own version of each
# function returned for the same input (server.py before the move, run on a scratch config); a roster, the contact lookups and the wait-basis gate are the server's names replaced for a case, the way a suite does.
H = update
from fastmcp.exceptions import ToolError
import contextlib
Q = "?"
ROSTER = {"alpha-main", "beta-builder", "gamma-engineer"}

@contextlib.contextmanager
def patched(**kv):
    """The server's own names replaced for a case (the service looks each one up when it is called), put back after."""
    old = {k: getattr(server, k) for k in kv}
    for k, v in kv.items(): setattr(server, k, v)
    try: yield
    finally:
        for k, v in old.items(): setattr(server, k, v)

def stale(was, new, writer, naming=(), passed=False, old_mark=None):
    meta = dict(new)
    if old_mark is not None: meta["next_stale"] = old_mark
    with patched(_session_roster=lambda: ROSTER):
        H._mark_next_stale({"status": "open", "metadata": was}, {"status": "open", "metadata": new}, meta, writer, list(naming), passed)
    mark = meta.get("next_stale")
    return None if mark is None else {**mark, "at": type(mark["at"]).__name__}

BASE = {"mover": "alpha-main", "next": "alpha-main: begin"}
def handoff(was, meta, next_, writer):
    with patched(_session_roster=lambda: ROSTER):
        return H._handoff_to(was, meta, next_, writer)

def contact(meta, project, fronts=(), main="", alive=True):
    with patched(_contact_fronts=lambda p: list(fronts) if p == project else [], _main_agent=lambda p: main if p == project else "", _contact_alive=lambda c: alive,
                 _contact_same=lambda a, b: bool(a) and a == b):
        return H._contact_after_move(meta, project)

LOGS = "alpha-main: collect the logs until 2099-03-02, then review"
LIVE = {"mover": "alpha-main", "next": "alpha-main: begin", "state": "doing"}
GATED = []                                                   # what the basis gate was asked: (basis, wake)
def _pass(item, basis, wake, held=False): GATED.append((basis, wake))
def _refuse(item, basis, wake, held=False): raise ToolError("Refused: the basis gate says no")
def loose(base, new, next_after="", description="", wake_in="", gate=_pass):
    """The item as it stood (`base`) and the metadata the write leaves (`base` + `new`); the basis gate (its own 365-day reach moves with the clock) is a stub that passes or refuses."""
    GATED.clear()
    real_basis = gates.gate_wait_basis
    gates.gate_wait_basis = gate                           # a gate is replaced on its owner, service/gates.py
    try:
        got = H._fix_loose_reason({"status": "open", "metadata": dict(base)}, {**base, **new}, next_after, description, wake_in)
    finally:
        gates.gate_wait_basis = real_basis
    return got, list(GATED)

CASES = [
    ("stale: a wake moved by a session that is neither the mover nor named by next marks next", lambda: stale(BASE, {**BASE, "wake": "2099-03-02"}, "beta-builder"), {'by': 'beta-builder', 'fields': ['wake'], 'at': 'float'}),
    ("stale: the fields add to the mark already there", lambda: stale(BASE, {**BASE, "wake": "2099-03-02"}, "beta-builder", old_mark={"by": "x", "fields": ["needs"], "at": 1.0}), {'by': 'beta-builder', 'fields': ['needs', 'wake'], 'at': 'float'}),
    ("stale: the mover's own write marks nothing", lambda: stale(BASE, {**BASE, "wake": "2099-03-02"}, "alpha-main"), None),
    ("stale: a writer the stored next names marks nothing", lambda: stale({**BASE, "next": "beta-builder: review"}, {**BASE, "next": "beta-builder: review", "wake": "2099-03-02"}, "beta-builder"), None),
    ("stale: a write that passes next clears the mark", lambda: stale(BASE, {**BASE, "wake": "2099-03-02"}, "beta-builder", passed=True, old_mark={"by": "x", "fields": ["wake"], "at": 1.0}), None),
    ("stale: nothing it watches changed", lambda: stale(BASE, {**BASE}, "beta-builder"), None),
    ("stale: needs added by the writer", lambda: stale(BASE, {**BASE, "needs": ["decision"]}, "beta-builder"), {'by': 'beta-builder', 'fields': ['needs'], 'at': 'float'}),
    ("stale: needs the server itself named are no change", lambda: stale(BASE, {**BASE, "needs": ["gamma-engineer"]}, "beta-builder", naming=["gamma-engineer"]), None),
    ("stale: a hold set", lambda: stale(BASE, {**BASE, "hold": True}, "beta-builder"), {'by': 'beta-builder', 'fields': ['hold'], 'at': 'float'}),
    ("handoff: the sessions the new next names, sorted, never the mover or the writer", lambda: handoff(BASE, BASE, "alpha-main: begin\ngamma-engineer: review it\nbeta-builder: build it", "delta"), ['beta-builder', 'gamma-engineer']),
    ("handoff: the writer is left out", lambda: handoff(BASE, BASE, "gamma-engineer: review it\nbeta-builder: build it", "beta-builder"), ['gamma-engineer']),
    ("handoff: a session the stored next already named is left out", lambda: handoff({**BASE, "next": "beta-builder: earlier"}, BASE, "beta-builder: again\ngamma-engineer: review", "delta"), ['gamma-engineer']),
    ("handoff: a session already in needs is left out", lambda: handoff({**BASE, "needs": ["gamma-engineer"]}, {**BASE, "needs": ["gamma-engineer"]}, "gamma-engineer: review\nbeta-builder: build", "delta"), ['beta-builder']),
    ("handoff: an empty next hands nothing", lambda: handoff(BASE, BASE, "  ", "delta"), []),
    ("handoff: a name that is no session on the roster is no hand-off", lambda: handoff(BASE, BASE, "stranger: do it", "delta"), []),
    ("contact: a stored contact that is a front agent of the new project stays", lambda: contact({"contact": "alpha-main", "owner": "o"}, "projects/new", fronts=["alpha-main"], main="new-main"), 'alpha-main'),
    ("contact: the creator, while it is a front agent, stays the contact", lambda: contact({"contact": "ops-creator", "owner": "ops-creator"}, "projects/new", main="new-main"), 'ops-creator'),
    ("contact: the creator that is no longer alive gives way to the new project's -main", lambda: contact({"contact": "ops-creator", "owner": "ops-creator"}, "projects/new", main="new-main", alive=False), 'new-main'),
    ("contact: neither -> the new project's -main agent", lambda: contact({"contact": "stale-one", "owner": "o"}, "projects/new", main="new-main"), 'new-main'),
    ("contact: no -main either -> empty", lambda: contact({}, "projects/new"), ''),
    ("doing note: a doing item whose next reads as a wait", lambda: H._doing_wait_note({"state": "doing"}, "alpha-main: wait until 2099-03-02 for the vendor's reply"), '\n(note: this item is doing, but its next reads as a wait (until a time or day), not work in hand; a doing item that waits shows as on an agent while nobody works it. Park it this turn with update(hold=true, until="<the time it waits for>", wait_basis="<what it waits on, with its date YYYY-MM-DD>"))'),
    ("doing note: a held item gets none", lambda: H._doing_wait_note({"state": "doing", "hold": True}, "alpha-main: wait until 2099-03-02 for the vendor's reply"), ''),
    ("doing note: work in hand gets none", lambda: H._doing_wait_note({"state": "doing"}, "alpha-main: write the parser"), ''),
    ("doing note: no next, none", lambda: H._doing_wait_note({"state": "doing"}), ''),
    ("loose: a hold with a wake and no reason takes its next's window line", lambda: loose(LIVE, {"hold": True, "wake": "2099-03-02"}, LOGS, "", "2099-03-02"), (('collect the logs until 2099-03-02, then review', ('\n(fixed: this hold had a wake and no wait reason, and your next says what it waits for ("collect the logs until 2099-03-02, then review"), so that line is the wait_basis. Send wait_basis="<what it waits on, with its date YYYY-MM-DD>" to use other words: the server then leaves the field alone)', '2099-03-02', 'wait reason: the hold had a wake and no reason; the next line "collect the logs until 2099-03-02, then review" is its wait_basis. A wait_basis sent in a later write replaces it')), [('collect the logs until 2099-03-02, then review', '2099-03-02')])),
    ("loose: the description is read when next says nothing of the wait", lambda: loose(LIVE, {"hold": True}, "alpha-main: begin", "- Goal: collect the logs until 2099-03-02, then review", "2099-03-02"), (('collect the logs until 2099-03-02, then review', ('\n(fixed: this hold had a wake and no wait reason, and your description says what it waits for ("collect the logs until 2099-03-02, then review"), so that line is the wait_basis. Send wait_basis="<what it waits on, with its date YYYY-MM-DD>" to use other words: the server then leaves the field alone)', '2099-03-02', 'wait reason: the hold had a wake and no reason; the description line "collect the logs until 2099-03-02, then review" is its wait_basis. A wait_basis sent in a later write replaces it')), [('collect the logs until 2099-03-02, then review', '2099-03-02')])),
    ("loose: next's line wins over the description's", lambda: loose(LIVE, {"hold": True}, LOGS, "- Goal: wait until 2099-03-02 for the vendor", "2099-03-02"), (('collect the logs until 2099-03-02, then review', ('\n(fixed: this hold had a wake and no wait reason, and your next says what it waits for ("collect the logs until 2099-03-02, then review"), so that line is the wait_basis. Send wait_basis="<what it waits on, with its date YYYY-MM-DD>" to use other words: the server then leaves the field alone)', '2099-03-02', 'wait reason: the hold had a wake and no reason; the next line "collect the logs until 2099-03-02, then review" is its wait_basis. A wait_basis sent in a later write replaces it')), [('collect the logs until 2099-03-02, then review', '2099-03-02')])),
    ("loose: an item the owner moves is left to the refusal", lambda: loose({**LIVE, "mover": server._model.owner_display()}, {"hold": True}, LOGS, "", "2099-03-02"), (('', ('', '', '')), [])),
    ("loose: a reason already stored for the wake is left alone", lambda: loose({**LIVE, "wake": "2099-03-02", "wait_basis": {"text": "vendor", "wake": "2099-03-02"}}, {"hold": True}, LOGS, "", ""), (('', ('', '', '')), [])),
    ("loose: a wait that is the owner's decision is left alone", lambda: loose({**LIVE, "needs": ["decision"]}, {"hold": True}, LOGS, "", "2099-03-02"), (('', ('', '', '')), [])),
    ("loose: a basis the gate refuses is no fix (the refusal stays)", lambda: loose(LIVE, {"hold": True}, LOGS, "", "2099-03-02", gate=_refuse), (('', ('', '', '')), [])),
    ("loose: no wake at all",lambda: loose(LIVE, {"hold": True}, LOGS, "", ""), (('', ('', '', '')), [])),
    ("loose: no line that reads as the wake's own day", lambda: loose(LIVE, {"hold": True}, "alpha-main: begin", "- Goal: finish", "2099-03-02"), (('', ('', '', '')), [])),
    ("time wait: an open item the model reads as a wait on a time", lambda: H._reads_time_wait({"status": "open", "metadata": {"mover": "alpha-main", "wait_kind": "time", "until": "2099-03-02", "phase": "waiting"}}), True),
    ("time wait: a closed item is none", lambda: H._reads_time_wait({"status": "completed", "metadata": {"mover": "alpha-main", "wait_kind": "time", "until": "2099-03-02", "phase": "waiting"}}), False),
    ("time wait: an item in work is none", lambda: H._reads_time_wait({"status": "open", "metadata": {"mover": "alpha-main"}}), False),
    ("time wait: a wait on an event is none", lambda: H._reads_time_wait({"status": "open", "metadata": {"mover": "alpha-main", "wait_kind": "event", "phase": "waiting"}}), False),
]
for label, thunk, want in CASES:
    try: got = thunk()
    except Exception as e: got = f"RAISED {e!r}"
    check(f"9 {label}", got == want, got)
check("9 …and the cases are not a few (each helper has a non-default case and an edge)", len(CASES) >= 36, len(CASES))
real_nag = page_debts._nag
page_debts._nag = lambda owner="": f"<nag for {owner!r}>"
try: via_table = tbl.nag("wr3-owner")
finally: page_debts._nag = real_nag
check("10 the nag is page_debts' own function looked up at each call (a patch of its owner after the install reaches the update)", via_table == "<nag for 'wr3-owner'>", via_table)
real_gate = server._gate_subject
server._gate_subject = lambda *a, **k: "<patched gate>"
try: via_gate = tbl.gate_subject("x")
finally: server._gate_subject = real_gate
check("10 …and a gate that stays on the server is looked up late too (a suite's patch of the server's name reaches the update)", via_gate == "<patched gate>", via_gate)
real_upd = server._update
server._update = lambda *a, **k: "<patched update>"
try:
    try: via_update = tbl.update("a1")
    except Exception as e: via_update = f"raised {e!r}"
finally: server._update = real_upd
check("10 the complete reaches the server's `_update` by a late lookup (a suite that replaces it there still reaches the close)", via_update == "<patched update>", via_update)
check("10 no flag and no notice is a hook of the update: the flags are service/writes.py's and the notices service/telling.py's, each read on its module", not ({"session_next", "reformat", "terminal_row", "question", "close_was_set"} | set(REAL_TELLING) | {"quiet"}) & {f.name for f in dataclasses.fields(update.Hooks)}, sorted({f.name for f in dataclasses.fields(update.Hooks)} & ({"session_next", "reformat", "terminal_row", "question", "close_was_set", "quiet"} | set(REAL_TELLING))))
check("10 the zone the confirm reply is told in is the server's own ZONE, looked up when the reply is made", tbl.zone() is server.ZONE, tbl.zone())
real_zone = server.ZONE
server.ZONE = datetime.timezone(datetime.timedelta(hours=-5))
try: seen_zone = tbl.zone()
finally: server.ZONE = real_zone
check("10 …so a later change of it reaches the update", seen_zone == datetime.timezone(datetime.timedelta(hours=-5)), seen_zone)

# ---------------------------------------------------------------- 11. the layers
src = pathlib.Path(STACK, "stackshot/service/update.py").read_text(encoding="utf-8")
tree = ast.parse(src)
imps = [n.module if isinstance(n, ast.ImportFrom) else a.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in (n.names if isinstance(n, ast.Import) else [n])]
check("11 service/update.py imports nothing from web/", not [m for m in imps if m and m.startswith("stackshot.web")], [m for m in imps if m and m.startswith("stackshot.web")])
srv = ast.parse(pathlib.Path(STACK, "stackshot/web/server.py").read_text(encoding="utf-8"))
defs = {n.name for n in srv.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
MOVED = ("_update_unlocked", "_update_locked", "_completion_anchor_prompt", "_handover_by_hand", "_wait_is_bare", "_hands_on", "_retired_note", "_next_names_session", "_wait_refs",
         "_stale_wait_notes", "_mark_next_stale", "_handoff_to", "_contact_after_move", "_doing_wait_note", "_fix_loose_reason", "_reads_time_wait")
check("11 web/server.py defines none of the moved bodies and keeps no copy under their old names", not (defs & set(MOVED)), sorted(defs & set(MOVED)))
here = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
check("11 each of them is defined once, in service/update.py (with the public names for the three writes)", {"update_unlocked", "_completion_anchor_prompt", "_handover_by_hand", "_wait_is_bare", "_hands_on", "_retired_note", "_next_names_session", "_wait_refs", "_stale_wait_notes",
      "_mark_next_stale", "_handoff_to", "_contact_after_move", "_doing_wait_note", "_fix_loose_reason", "_reads_time_wait", "update_item", "complete_item", "confirm_item"} <= here, sorted(here))
_tool_src = {rel: pathlib.Path(STACK, rel).read_text(encoding="utf-8") for rel in ("stackshot/web/server.py", "stackshot/web/tools/complete.py", "stackshot/web/tools/update.py")}
_tool_src_of = {}
tools = {}
for _rel, _src in _tool_src.items():
    for n in ast.parse(_src).body:
        if isinstance(n, ast.FunctionDef) and n.name in ("stackshot_complete", "stackshot_confirm", "stackshot_update", "_update"):
            tools[n.name] = n; _tool_src_of[n.name] = _src
def calls(fn): return {f"{c.func.value.id}.{c.func.attr}" for c in ast.walk(fn) if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and isinstance(c.func.value, ast.Name)}
check("11 the complete tool is a thin wrapper: its identity checks, then the service's complete", "_update_svc.complete_item" in calls(tools["stackshot_complete"]), calls(tools["stackshot_complete"]))
check("11 the confirm tool is a thin wrapper: its identity checks, then the service's confirm", "_update_svc.confirm_item" in calls(tools["stackshot_confirm"]), calls(tools["stackshot_confirm"]))
check("11 the server's `_update` is a thin wrapper over the service's entry", "_update_svc.update_item" in calls(tools["_update"]), calls(tools["_update"]))
check("11 the update tool still goes through `_update` (its own checks stay on the server)", any(isinstance(c, ast.Name) and c.id == "_update" for c in ast.walk(tools["stackshot_update"])), None)
check("11 the tools' bodies stay short", all(len(ast.get_source_segment(_tool_src_of[n], tools[n]).splitlines()) < 400 for n in ("stackshot_complete", "stackshot_confirm", "_update")), None)

writes.save = real_save
print(f"update write scenario: {len(ran) - len(fails)}/{len(ran)} checks")
if fails: print(f"FAILED {len(fails)}"); sys.exit(1)
print(f"ok: update write scenario, {len(ran)} checks")
