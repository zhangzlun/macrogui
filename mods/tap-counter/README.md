# tap-counter

A small demo mod for Claude Code: a counter you drive with `/tap`.

- `/tap` adds one, `/tap 5` adds five, `/tap 歸零` resets, `/tap panel` opens the pane.
- The pane and the band above the prompt draw only in a local Claude Code session
  (terminal or the desktop app's local Code tab). In a cloud session viewed from the
  web or mobile app, only the text replies of `/tap` show.

Try it locally from the repository root:

```
claude --plugin-dir mods/tap-counter
```
