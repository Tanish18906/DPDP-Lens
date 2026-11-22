# 14 Git rules

This file overrides every other file on git. It depends on WHICH TOOL you are, not which person is using you.

## Who may commit and push
| Who | Commit and push |
|-----|-----------------|
| Claude (Claude Code, any Claude model) | NEVER |
| Antigravity (AGY) agent | Yes |
| Tanish and Anmol (humans) | Yes |

If you are Claude, follow section A. If you are the Antigravity agent, follow section B. Either one: if you are not sure which tool you are, behave as Claude (section A) and ask the human.

## A. If you are Claude (Claude Code)

### You must NOT run
git add, git commit, git push, git pull, git fetch, git rebase, git merge, git reset, git checkout (including switching branches or discarding changes), git restore, git stash, git tag, git branch (create or delete), git init, git remote add or set-url, git config, git cherry-pick, git revert, git clean, git rm, git mv, and any `gh` command that creates or changes a repo, PR, issue or branch.
Do not create, edit or delete anything inside .git or any git hook. Keep any auto-commit or checkpoint feature off.

### You MAY run (read only)
git status, git diff, git log, git show, git branch (list only), git remote -v.

### What this changes in other docs
- AGENTS.md and docs/13-work-split.md say "commit and push" at the end of a phase. For you, replace that with "hand over to the human".
- docs/10-implementation-plan.md agent rule 3: same replacement.
- Any "commit" or "push" wording in docs 05, 06, 09 is an instruction to the human when you are Claude.
- Do not add "Co-Authored-By" or "Generated with" lines anywhere. README still declares the AI tools used.

### End of every phase (Claude)
1. Run the gate and the tests. Fix failures. Never claim a phase is done if the gate failed.
2. Update your STATUS file (docs/STATUS-tanish.md). This is a normal file edit.
3. Run `git status` (read only) and list the changed files.
4. Reply with this block and nothing long:

        Phase <id> done. Gate: <command> -> <result>.
        Changed files:
        - <path>
        Suggested commit message: <plain sentence>
        For you to run (I will not):
          git add <paths>
          git commit -m "<message>"
          git pull --rebase origin main
          git push origin main
        Next phase: <id and name>. Say "next" when you have committed.

5. STOP. Do not start the next phase.

### If something goes wrong (Claude)
The human runs all git commands. You may read an error, explain it, and edit conflicted FILES to resolve markers, but the human runs `git add`, `git rebase --continue` and the rest. If you ever find that you made a commit or push by mistake, say so at once and do not try to fix it with reset, amend or force push.

## B. If you are the Antigravity (AGY) agent

You may commit and push, with these limits:
- Commit only your own folders and your own STATUS file (docs/STATUS-anmol.md). Never commit .venv, node_modules, .env, scan.json, zip files or secrets.
- At the end of a phase, after the gate passes: `git add` your own paths, commit with a plain message ("add dashboard scaffold"), `git pull --rebase origin main`, then push to main.
- Per AGENTS.md ask-before rules, ask the human "OK to push?" before each push, unless the human has told you in this session to push without asking.
- Never force push. Never run reset --hard, clean, or rebase on shared history. If the rebase conflicts, stop, show the conflict and ask the human.
- Never touch the other person's folders or STATUS file.
- Do not add "Co-Authored-By" lines unless the human asks.
- After pushing, reply with the 6 line phase report from docs/13-work-split.md and STOP. Do not start the next phase.

## For the humans (everyone)
- Commit after every phase and before saying "next".
- Always `git pull --rebase origin main` before `git push origin main`.
- When Claude hands over a phase, you run the git commands in the block it gives you.
- Commit messages in plain words.
