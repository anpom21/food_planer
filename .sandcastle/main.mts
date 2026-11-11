// Parallel Planner with Review — four-phase orchestration loop
//
// This template drives a multi-phase workflow:
//   Phase 1 (Plan):             An opus agent analyzes open issues, builds a
//                               dependency graph, and outputs a <plan> JSON
//                               listing unblocked issues with branch names.
//   Phase 2 (Execute + Review): For each issue, a sandbox is created via
//                               createSandbox(). The implementer runs first.
//                               If it produces commits, a reviewer runs in the
//                               same sandbox on the same branch (1 iteration).
//                               All issue pipelines run concurrently via
//                               Promise.allSettled().
//   Phase 3 (Merge):            A single agent merges all completed branches
//                               into the current branch.
//
// The outer loop repeats up to MAX_ITERATIONS times so that newly unblocked
// issues are picked up after each round of merges.
//
// Usage:
//   npx tsx .sandcastle/main.mts
// Or add to package.json:
//   "scripts": { "sandcastle": "npx tsx .sandcastle/main.mts" }

import { execFileSync } from "node:child_process";
import * as sandcastle from "@ai-hero/sandcastle";
import { docker } from "@ai-hero/sandcastle/sandboxes/docker";
import { z } from "zod";

// The planner emits its plan as JSON inside <plan> tags; Output.object extracts
// and validates it against this schema. We use Zod here, but any Standard
// Schema validator works just as well — Valibot, ArkType, etc. See
// https://standardschema.dev.
const planSchema = z.object({
  issues: z.array(
    z.object({ id: z.string(), title: z.string(), branch: z.string() }),
  ),
});

type PlannedIssue = z.infer<typeof planSchema>["issues"][number];

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

// Maximum number of plan→execute→merge cycles before stopping.
// Raise this if your backlog is large; lower it for a quick smoke-test run.
const MAX_ITERATIONS = 10;

// Cap on implementer iterations. Deliberately not huge: an agent that has lost
// the plot burns this budget in full, and in practice a well-scoped issue lands
// in a handful of iterations.
const IMPLEMENT_MAX_ITERATIONS = 25;

// Hooks run inside the sandbox before the agent starts each iteration.
// This project is Python (uv) with a React frontend, so both halves of the
// toolchain have to be present before any agent can run the feedback loops.
// Without this every agent rediscovers the setup from scratch, which is pure
// token burn.
const hooks = {
  sandbox: {
    onSandboxReady: [
      { command: "uv sync" },
      { command: "npm install --prefix frontend" },
    ],
  },
};

// Copy node_modules from the host into the worktree before each sandbox
// starts. Avoids a full npm install from scratch; the hook above handles
// platform-specific binaries and any packages added since the last copy.
const copyToWorktree = ["node_modules", "frontend/node_modules"];

// ---------------------------------------------------------------------------
// Git helpers
//
// Branch state is the orchestrator's source of truth for "has this issue
// already been implemented?". It survives a crashed run, unlike anything held
// in memory, and needs no state file to drift out of sync.
// ---------------------------------------------------------------------------

function git(...args: string[]): string {
  return execFileSync("git", args, { encoding: "utf8" }).trim();
}

function branchExists(branch: string): boolean {
  try {
    git("rev-parse", "--verify", "--quiet", `refs/heads/${branch}`);
    return true;
  } catch {
    return false;
  }
}

/** Commits on `branch` that are not yet on HEAD — i.e. work awaiting merge. */
function unmergedCommitCount(branch: string): number {
  if (!branchExists(branch)) return 0;
  const log = git("log", "--oneline", `HEAD..${branch}`);
  return log === "" ? 0 : log.split("\n").length;
}

/** True when the branch exists and everything on it has already landed. */
function isFullyMerged(branch: string): boolean {
  return branchExists(branch) && unmergedCommitCount(branch) === 0;
}

/** A merge stopped partway leaves MERGE_HEAD behind and poisons later runs. */
function mergeInProgress(): boolean {
  try {
    git("rev-parse", "--verify", "--quiet", "MERGE_HEAD");
    return true;
  } catch {
    return false;
  }
}

const planFingerprint = (issues: PlannedIssue[]) =>
  issues
    .map((i) => i.id)
    .sort()
    .join(",");

// ---------------------------------------------------------------------------
// Main loop
// ---------------------------------------------------------------------------

// The previous round's issue set. If a round plans exactly the same issues as
// the one before it and nothing merged, we are looping without progress —
// stop rather than burn the remaining iterations re-deriving the same result.
let previousFingerprint: string | null = null;

for (let iteration = 1; iteration <= MAX_ITERATIONS; iteration++) {
  console.log(`\n=== Iteration ${iteration}/${MAX_ITERATIONS} ===\n`);

  // A merge left half-finished by an earlier run (crash, session limit) blocks
  // every git operation that follows. Surface it here rather than letting the
  // merge agent trip over it several minutes and several agents later.
  if (mergeInProgress()) {
    console.error(
      "A merge is already in progress (.git/MERGE_HEAD exists).\n" +
        "Resolve the conflicts and commit, or run `git merge --abort`, then re-run.",
    );
    break;
  }

  // -------------------------------------------------------------------------
  // Phase 1: Plan
  //
  // The planning agent (opus, for deeper reasoning) reads the open issue list,
  // builds a dependency graph, and selects the issues that can be worked in
  // parallel right now (i.e., no blocking dependencies on other open issues).
  //
  // It outputs a <plan> JSON block — Output.object parses and validates it.
  // -------------------------------------------------------------------------
  const plan = await sandcastle.run({
    hooks,
    sandbox: docker(),
    name: "planner",
    // One iteration is enough: the planner just needs to read and reason,
    // not write code. (Structured output requires maxIterations: 1.)
    maxIterations: 1,
    // Opus for planning: dependency analysis benefits from deeper reasoning.
    agent: sandcastle.claudeCode("claude-opus-4-8"),
    promptFile: "./.sandcastle/plan-prompt.md",
    // Extract and validate the <plan> JSON into a typed object. Throws
    // StructuredOutputError if the tag is missing, the JSON is malformed, or
    // validation fails — which aborts the loop.
    output: sandcastle.Output.object({ tag: "plan", schema: planSchema }),
  });

  const planned: PlannedIssue[] = plan.output.issues;

  if (planned.length === 0) {
    // No unblocked work — either everything is done or everything is blocked.
    console.log("No unblocked issues to work on. Exiting.");
    break;
  }

  // An issue whose branch is fully merged is finished; it is only still in the
  // plan because nobody closed it (the merge phase closes issues, so a crash
  // there leaves them open). Re-implementing it is exactly the loop that wastes
  // a run, so drop it here and say so.
  const alreadyLanded = planned.filter((i) => isFullyMerged(i.branch));
  const issues = planned.filter((i) => !isFullyMerged(i.branch));

  for (const issue of alreadyLanded) {
    console.log(
      `  ⤳ Skipping ${issue.id}: ${issue.branch} is already merged into HEAD. ` +
        `Close it with: gh issue close ${issue.id} --comment "Completed by Sandcastle"`,
    );
  }

  if (issues.length === 0) {
    console.log(
      "\nEvery planned issue is already merged. Close them (see above) so the " +
        "planner stops returning them, then re-run.",
    );
    break;
  }

  // Guard against a round that plans exactly what the last round planned. On
  // its own this is not proof of a stall, but combined with the merge phase
  // below (which stops the loop when nothing merges) it bounds the damage.
  const fingerprint = planFingerprint(issues);
  if (fingerprint === previousFingerprint) {
    console.error(
      `\nPlanned the same issue set as the previous round (${fingerprint}) ` +
        "with nothing merged in between. Stopping to avoid an unproductive loop.",
    );
    break;
  }
  previousFingerprint = fingerprint;

  console.log(
    `Planning complete. ${issues.length} issue(s) to work in parallel:`,
  );
  for (const issue of issues) {
    console.log(`  ${issue.id}: ${issue.title} → ${issue.branch}`);
  }

  // -------------------------------------------------------------------------
  // Phase 2: Execute + Review
  //
  // For each issue, create a sandbox via createSandbox() so the implementer
  // and reviewer share the same sandbox instance per branch. The implementer
  // runs first; if it produces commits, the reviewer runs in the same sandbox.
  //
  // Promise.allSettled means one failing pipeline doesn't cancel the others.
  // -------------------------------------------------------------------------

  const settled = await Promise.allSettled(
    issues.map(async (issue) => {
      // Work already sitting on the branch from an earlier run counts as done.
      // Without this, an issue that was implemented but never merged (because
      // the merge phase crashed) gets a fresh implementer every round, which
      // correctly concludes "nothing to do", produces no commits, and leaves
      // the loop exactly where it started.
      const carriedOver = unmergedCommitCount(issue.branch);
      if (carriedOver > 0) {
        console.log(
          `  ↺ ${issue.id}: ${issue.branch} already carries ${carriedOver} ` +
            "unmerged commit(s) from an earlier run — going straight to merge.",
        );
        return { completed: true, producedCommits: false };
      }

      const sandbox = await sandcastle.createSandbox({
        branch: issue.branch,
        sandbox: docker(),
        hooks,
        copyToWorktree,
      });

      try {
        // Run the implementer
        const implement = await sandbox.run({
          name: "implementer",
          maxIterations: IMPLEMENT_MAX_ITERATIONS,
          agent: sandcastle.claudeCode("claude-opus-4-8"),
          promptFile: "./.sandcastle/implement-prompt.md",
          promptArgs: {
            TASK_ID: issue.id,
            ISSUE_TITLE: issue.title,
            BRANCH: issue.branch,
          },
        });

        // Only review if the implementer produced commits
        if (implement.commits.length > 0) {
          await sandbox.run({
            name: "reviewer",
            maxIterations: 1,
            agent: sandcastle.claudeCode("claude-opus-4-8"),
            promptFile: "./.sandcastle/review-prompt.md",
            promptArgs: {
              BRANCH: issue.branch,
            },
          });
        }

        // Completion is what the agent SAYS, not what the diff shows. An agent
        // that verifies the work is already correct and declines to fabricate
        // an empty commit has completed the task; judging by commit count
        // alone marks it a failure and replans it forever.
        return {
          completed: implement.completionSignal !== undefined,
          producedCommits: implement.commits.length > 0,
        };
      } finally {
        await sandbox.close();
      }
    }),
  );

  // Log any agents that threw (network error, sandbox crash, etc.).
  for (const [i, outcome] of settled.entries()) {
    if (outcome.status === "rejected") {
      console.error(
        `  ✗ ${issues[i]!.id} (${issues[i]!.branch}) failed: ${outcome.reason}`,
      );
    }
  }

  // A branch goes to the merge phase when it has commits that are not on HEAD.
  // That covers commits made this round and commits carried over from a round
  // whose merge never finished — and it excludes an agent that signalled
  // completion without changing anything, which has nothing to merge.
  const completedIssues = settled
    .map((outcome, i) => ({ outcome, issue: issues[i]! }))
    .filter(
      (entry) =>
        entry.outcome.status === "fulfilled" &&
        entry.outcome.value.completed &&
        unmergedCommitCount(entry.issue.branch) > 0,
    )
    .map((entry) => entry.issue);

  const completedBranches = completedIssues.map((i) => i.branch);

  console.log(
    `\nExecution complete. ${completedBranches.length} branch(es) with commits:`,
  );
  for (const branch of completedBranches) {
    console.log(`  ${branch}`);
  }

  if (completedBranches.length === 0) {
    // All agents ran but none left anything to merge. Continuing would replan
    // the same issues and produce the same nothing, so stop and let a human
    // look at the logs.
    console.error(
      "No commits produced and nothing carried over. Stopping — re-running " +
        "would replan the same issues. Check .sandcastle/logs/.",
    );
    break;
  }

  // -------------------------------------------------------------------------
  // Phase 3: Merge
  //
  // One agent merges all completed branches into the current branch,
  // resolving any conflicts and running tests to confirm everything works.
  //
  // The {{BRANCHES}} and {{ISSUES}} prompt arguments are lists that the agent
  // uses to know which branches to merge and which issues to close.
  // -------------------------------------------------------------------------
  await sandcastle.run({
    hooks,
    sandbox: docker(),
    name: "merger",
    maxIterations: 1,
    agent: sandcastle.claudeCode("claude-opus-4-8"),
    promptFile: "./.sandcastle/merge-prompt.md",
    promptArgs: {
      // A markdown list of branch names, one per line.
      BRANCHES: completedBranches.map((b) => `- ${b}`).join("\n"),
      // A markdown list of issue IDs and titles, one per line.
      ISSUES: completedIssues.map((i) => `- ${i.id}: ${i.title}`).join("\n"),
    },
  });

  // The merge agent is the single point where issues get closed, so a crash
  // here (session limit, timeout) strands finished work. Say so loudly — the
  // next run's guards will skip the implementers, but only a human can close
  // the issues and finish the merge.
  if (mergeInProgress()) {
    console.error(
      "\nThe merge phase left a merge in progress. Resolve the conflicts and " +
        "commit (or `git merge --abort`), then close the merged issues.",
    );
    break;
  }

  const stillUnmerged = completedIssues.filter(
    (i) => unmergedCommitCount(i.branch) > 0,
  );
  if (stillUnmerged.length > 0) {
    console.error(
      `\nThe merge phase did not land: ${stillUnmerged
        .map((i) => i.branch)
        .join(", ")}. They will be retried on the next round.`,
    );
  }

  // Only forgive a repeated plan when something actually landed. A merge agent
  // that reports success without merging anything is precisely the stall this
  // guard exists to catch, so we check the branches rather than trust the run.
  const landed = stillUnmerged.length < completedIssues.length;
  if (landed) {
    // Real progress: the next round's plan is allowed to overlap this one,
    // since merging can legitimately unblock adjacent issues.
    previousFingerprint = null;
    console.log("\nBranches merged.");
  } else {
    console.error(
      "\nThe merge phase landed nothing. Keeping the loop guard armed — if " +
        "the next round plans the same issues, it will stop.",
    );
  }
}

console.log("\nAll done.");
