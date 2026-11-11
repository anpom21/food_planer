# FIRST: FINISH ANY MERGE ALREADY IN PROGRESS

Before anything else, run `git status`. A previous run can die partway through a
merge (timeout, session limit) and leave `.git/MERGE_HEAD` behind, which blocks
every merge that follows.

If a merge is in progress:

1. Check whether the conflicted files still contain markers (`<<<<<<<`). A dead
   run often wrote the resolution but never staged it — in that case just verify
   the content, `git add` the files, and commit.
2. Otherwise resolve the conflicts, verify, and commit.
3. Only then continue with the branches below.

Never start a new merge while one is in progress.

# TASK

Merge the following branches into the current branch:

{{BRANCHES}}

For each branch:

1. Run `git merge <branch> --no-edit`
2. If there are merge conflicts, resolve them intelligently by reading both sides and choosing the correct resolution
3. After resolving conflicts, verify with `uv run pytest` and `npm run typecheck --prefix frontend` (there is no root `npm test` script)
4. If tests fail, fix the issues before proceeding to the next branch

After all branches are merged, make a single commit summarizing the merge.

# CLOSE ISSUES

Do this as soon as each branch lands — do not batch it to the end of the run.
Closing the issue is what stops the planner from picking the same work up again
next round, so an unclosed issue for merged work sends the whole loop back
around. If you are running low on context or time, close what has merged before
starting another branch.

For each branch that was merged, close its issue using the following command:

`gh issue close <ID> --comment "Completed by Sandcastle"`

Here are all the issues:

{{ISSUES}}

Once you've merged everything you can, output <promise>COMPLETE</promise>.
