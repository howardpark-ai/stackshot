## description route
A ruling on a notice delivered for a project. The router rules every notice of every project by itself (rules in code,
then one thin call), so call this to overrule a ruling that was wrong. `notice` = the id at the end of the notice
("notice a1b2c3"); `ruling` = passed (handed to an agent: name it in `to`) | merged (folded into a digest) | held
(kept for later) | dropped (not worth anyone's attention); `reason` = one line {{OWNER}} can skim; `sender` = your own
session. Right call: route(notice="a1b2c3", ruling="passed", to="my-x", reason="belongs to the export work",
sender="my-x"). Call it once per notice, after acting on it; call it again to overrule an earlier ruling. The
project's routing page (behind its number in the board's anchors column) lists every notice with its ruling and
reason, and the board flags notices left without a ruling for over an hour.
