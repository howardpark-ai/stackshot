"""tests/_instance.py: the settings of an example instance, for the suites that test behaviour an instance sets itself.

The code carries no instance's values as defaults (machines, scopes, agents, the aliases a line of next opens with, ...); they are settings. A suite
whose checks are about what a configured instance does (an `AE:` line of next, the ssh form for box-a, the work, home and ops scopes) builds its config
and then passes the text through apply(): the values below are made-up test values. The owner's name is not set here (a suite sets `owner` itself where
it checks a text that names the owner). tests/neutral_install_scenario.py checks the example config on its own.

    toml = _instance.apply(toml)              # before the suite writes its config file
    toml = _instance.apply(toml, owner=True)  # a suite that does not set `owner` itself
    toml = _instance.apply(toml, login=True)  # a suite that checks the owner's GitHub login ([github] owner_login)
    toml = _instance.apply(toml, gbrain=True) # a suite that runs the gbrain-only tools with a fake `gb` (rename_page, page_keeper, page_debt)
    toml = _instance.apply(toml, keywords=True)  # a suite that checks the words of another language ([keywords.<feature>], Japanese here)

The text a suite starts from is base_toml(): the example config, read through the tracked link tests/example_base.toml (-> ../stackshot.example.toml)
and not by its own path. The selection of CI (tests/suitemap.py, *The example config* in its docstring) tells the two apart: a suite that reads the real
path is a direct reader of the example config and runs on every change to it; a suite that reads it through the link only uses its text as the base of
its own temp config, and runs on a change that alters an existing setting (not on a comment, nor on a key added). A suite that checks the example config
itself, or patches a setting of it the suite then asserts on, reads the real path (pathlib.Path(STACK, "stackshot.example.toml")).
"""
import os, pathlib, re

# the link, not the file it points to: the strace of the measured run records the path a process opens as it was written
EXAMPLE_BASE = pathlib.Path(os.path.abspath(__file__)).with_name("example_base.toml")


def base_toml() -> str:
    """The example config's text, read through tests/example_base.toml (see the docstring of this file)."""
    return EXAMPLE_BASE.read_text(encoding="utf-8")

# section -> {key: toml value}; a key that is not in its section yet is added right after the header
SETTINGS = {
    "instance": {"owner_aliases": '["AE", "オリバー"]'},
    "pages": {"dirs": '["projects", "ops"]', "template_page": '"projects/example"', "timeline_source": '"falcon-main"',
              "rules_line": '"- Rules: [`RULES_EXAMPLE.md`](https://github.com/example-owner/ops-hub/blob/main/docs/RULES_EXAMPLE.md), sections *notes* and *board*."'},
    "registries.projects": {"match": '["projects/{value}", "ops/{value}", "{value}"]'},
    "steps": {"owner_shell": '"powershell"', "bash_host": '"box-a"'},
    "terminal": {"fallback_project": '"projects/example-two"'},
    "runners": {"owner": '"example-owner"', "boxes": '["box-a", "box-b", "box-c"]', "local_box": '"box-a"'},
    "runners.ssh_hosts": {"box-b": '"box-b"', "box-c": '"box-c"'},
    "project_scopes": {"order": '["work", "home", "ops"]', "default": '"home"', "orgs": '["work", "home"]'},
    "project_agent": {"form_machines": '["box-a"]'},
    "model": {"rebullet_machines": '["box-a"]', "migration_machines": '["box-a"]',
              "migration_senders": '["falcon-redesign-engineer", "falcon-engineer"]'},
    "said": {"injected_prefixes": '["[auto-note]", "Relay note:"]',
             "injected_phrases": '["pasted by the relay tool"]'},
    "router": {"general_home": '"home-commons-main"', "general_ops": '"heron-main"', "general_work": '"projects/work-commons"'},
    "audit": {"agent": '"falcon-audit"', "builder": '"falcon-engineer"', "main": '"falcon-main"'},
    "gbrain": {"bin": '"~/.bun/bin/gbrain"'},
}
# The words of another language, for the suites that check the matchers [keywords.<feature>] extends (config.KEYWORDS lists every key). The tests use Japanese: its words have no
# spaces, its particles stick to the word before them, and it has three scripts, which is what the matchers must cope with. Each list ADDS to the English words.
KEYWORDS = {
    "keywords.step_commands": {
        "shell_names": '["パワーシェル", "パワーシェール", "ターミナル"]',
        "windows_words": '["ウィンドウズ", "ウインドウズ"]',
        "run_commands": '["実行して", "実行してください", "入力して", "入力してください", "貼り付けて"]',
        "after_command": '["実行", "入力", "貼り付け", "を実行", "を入力", "を貼り付け"]',
        "subject_markers": '["が"]',
        "pointer_patterns": r"""['(?:下|上)の(?:内容|説明|手順)?を?(?:参照|確認)', '説明(?:欄|文)?を?(?:参照|確認)', '(?:本文|詳細)を?(?:参照|確認)']""",
        "pane_cues": '["入力", "実行"]',
    },
    "keywords.router": {"decision": '["決定"]', "urgent": '["緊急", "至急"]'},
    "keywords.model_guards": {
        "wait_words": '["待機", "待つ"]',
        "overnight_words": '["一晩"]',
        "defer_after_id": '["が閉じたら", "が終わったら", "の完了後", "が完了したら", "以降", "までは", "まで", "の前に", "より前に"]',
    },
    "keywords.dates": {
        "month_suffix": '["月"]', "day_suffix": '["日"]', "week_suffix": '["週間"]', "later_words": '["後"]',
        "tomorrow": '["明日"]', "day_after_tomorrow": '["明後日"]', "next_week": '["来週"]', "next_month": '["来月"]',
    },
    "keywords.pages": {"board_label": '["ボード"]', "no_change": '["変更なし"]'},
    "keywords.rebullet": {"pronouns": '["彼の", "彼女", "彼ら", "それ"]', "negations": '["ない", "ません", "なかった"]', "negation_words": '["不"]'},
    "keywords.reports": {"ask_words": '["必要", "確認", "承認", "決定", "お願い", "検討", "選択", "意見"]'},
    "keywords.draft": {
        "stems": '["投稿", "送信", "転送", "貼り付け", "返信", "下書き", "メール", "メッセージ", "共有"]',
        "stem_patterns": r"""['送(?=[るりれ])']""",
        "standalone_stems": '["文書"]',
        "particles": '["を", "は", "が", "に"]',
        "ignore_phrases": '["画面共有"]',
    },
    "keywords.waiting": {"park_words": '["保留", "延期", "後で", "来月"]'},
    "keywords.server": {"command_cues": '["実行", "貼り付け"]'},
}
# the settings a flag of apply() adds: section -> {key: toml value}
FLAG_SETTINGS = {
    "owner": {"instance": {"owner": '"Oliver"'}},
    "login": {"github": {"owner_login": '"example-owner"'}},
    "gbrain": {"pages": {"flavor": '"gbrain"'}},
}
# Tables whose header line a suite's pattern anchors on (`(?m)^(\[audit\][^\n]*\n)enabled = false`): a key added right under the header would break it.
PINNED_TABLES = ("audit", "anchor_hub")
# NAMES THE SELECTION READS (tests/suitemap.py, *The example config*): SETTINGS, KEYWORDS, FLAG_SETTINGS, TABLES and PINNED_TABLES are read from this file
# by `ast.literal_eval` at the target commit, so they stay plain literals. A change to stackshot.example.toml selects the suites that read it through
# tests/example_base.toml unless it only adds or removes blank lines and plain prose comments; a comment that contains a word of one of these names (or of any
# key or table of the example) is not plain. Add what apply() touches to the constants and the selection follows. tests/suitemap_scenario.py runs apply() and
# fails when it changes a name the constants do not list; that holds for a `_set` or an append written in apply() itself, but a name dropped from a constant
# and from apply() together is not caught. PINNED_TABLES are the tables a suite's pattern anchors on by their header line.
# tables the example config does not carry (commented there), appended at the end
TABLES = '''
[project_scopes.by_prefix]
"ops/" = "ops"
[project_scopes.by_tag]
ops = "ops"
work = "work"
[job_gap.repos]
"example-owner/ops-hub" = "ops/general"
"howardpark-ai/salamander" = "projects/example-two"
"howardpark-ai/stackshot" = "projects/example"
[[router.watch]]
page = "projects/example-brain"
anchor = "github:example-upstream/tool#2"
agent = "kestrel-main"
[[router.quiet]]
page = "projects/example-site"
agent = "example-site-builder"
'''


def _set(toml: str, section: str, key: str, value: str) -> str:
    lines = toml.split("\n")
    head = f"[{section}]"
    start = next((i for i, ln in enumerate(lines) if ln.split("#")[0].strip() == head), None)
    if start is None and section.startswith("keywords."):        # a config that is not the example's text: the table is added at the end
        return toml.rstrip("\n") + f"\n[{section}]\n{key} = {value}\n"
    assert start is not None, f"no [{section}] in the config text"
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("[")), len(lines))
    for i in range(start + 1, end):
        if re.match(rf"{re.escape(key)}\s*=", lines[i]):
            lines[i] = f"{key} = {value}"
            return "\n".join(lines)
    lines.insert(start + 1, f"{key} = {value}")
    return "\n".join(lines)


def apply(toml: str, gbrain: bool = False, owner: bool = False, login: bool = False, keywords: bool = False) -> str:
    """The config text with the example-owner instance's settings on top. The owner's name is left to the suite unless owner=True (for a suite that does not set it itself).
    keywords=True also sets the Japanese words of KEYWORDS (a suite that checks what the words of another language add)."""
    for section, keys in SETTINGS.items():
        for key, value in keys.items():
            toml = _set(toml, section, key, value)
    if keywords:
        for section, keys in KEYWORDS.items():
            for key, value in keys.items():
                toml = _set(toml, section, key, value)
    for flag, on in (("owner", owner), ("login", login), ("gbrain", gbrain)):
        if on:
            for section, keys in FLAG_SETTINGS[flag].items():
                for key, value in keys.items():
                    toml = _set(toml, section, key, value)
    return toml.rstrip("\n") + "\n" + TABLES
