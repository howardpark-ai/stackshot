# fonts/

The code font of the board and the item pages (command blocks, inline code). The server serves it itself, at
`/fonts/D2Coding-Regular.woff2?v=<first 12 hex of the file's SHA-256>` (`stackshot/web/auth/signin.py` `_FONT_PATH`, public like the icons, kept a year
when `?v=` is the version of the bytes on disk), and `render.py` names it in an `@font-face` (`font-display:swap`) ahead of the
`ui-monospace,...` stack, which stays as the fallback.

- `D2Coding-Regular.woff2`: Naver's **D2Coding Ver 1.4.0 (20261003)**, regular weight, the non-ligature build, converted from TTF to WOFF2
  with fontTools, **not subsetted** (all of Hangul and the Latin, symbol and CJK glyphs it has). No code is bold, so no bold file.
- `OFL.txt`: the font's licence, as shipped in the release zip. D2Coding is under the SIL Open Font License 1.1 with Reserved Font Names
  "D2Coding" and "D2Coding-Bold"; the file keeps the font's own name table and design untouched.

Source: https://github.com/naver/d2-coding-font/releases/tag/VER1.4.0 (the repository was `naver/d2codingfont`),
asset `D2Coding-Ver1.4.0-20261003.zip`, SHA-256 `17e2da5e2879006eb725b87943f7988736ef8b6c9f8b84bc8e3bdbcb8dd46744`;
`D2Coding/D2Coding-Ver1.4.0-20261003.ttf` inside it, converted with
`uv run --with fonttools --with brotli fonttools ttLib.woff2 compress -o D2Coding-Regular.woff2 <that ttf>`.
`D2Coding-Regular.woff2` SHA-256: `76def7a188d179bb51e626731f6c2583e31b4ca37175175ed6f319aa713d951c`.

To replace it: put the new WOFF2 here under the same name (the `?v=` changes with its bytes) and update this note; `deploy.sh`
restarts the server when `fonts/*` changes.
