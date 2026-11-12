import { expect, test } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { E2E, run } from "./aip";

// A run started from another run's script (the aip repo's plan, R7): the server links the two, and each run's page
// says so, the parent listing the child under "started" and the child naming the run, step and pass that started it.

const PARENT = path.join(E2E, "orchestrated", "spawner");
const CHILD = path.join(E2E, "orchestrated", "echo");

function write(folder: string, files: Record<string, string>) {
  for (const [name, text] of Object.entries(files)) {
    fs.mkdirSync(path.dirname(path.join(folder, name)), { recursive: true });
    fs.writeFileSync(path.join(folder, name), text);
  }
}

test.beforeAll(() => {
  write(CHILD, {
    "procedure.aip": `Procedure echo
  "Say the message back."

Start "The message." {
  message: string
  Next_Step end
}

End "The message." {
  Read message
}
`,
  });
  write(PARENT, {
    "procedure.aip": `Procedure spawner
  "Start echo from a script."
  Requires python 3.10

Start "The message, and the folder of the procedure to start." {
  message: string
  child_folder: string
  Next_Step spawn
}

Execute spawn "Run the child with the message." {
  Read message, child_folder
  Run_Script scripts/spawn.py
  Produce child: string "The child's run id."
  Next_Step end
}

End "The child's run id." {
  Read child
}
`,
    "scripts/spawn.py": `import json, sys
import aip
state = json.load(sys.stdin)["state"]
done = aip.Client().run(state["child_folder"], {"message": state["message"]})
print(json.dumps({"child": done.run_id}))
`,
  });
});

test("a run its parent's script started is listed under the parent, and names it", async ({ page }) => {
  const parent = run(PARENT, { message: "hello from the parent", child_folder: CHILD }, { session: "orchestrated" });
  expect(parent.done).toBe(true);
  const parentId = parent.run_id as string;
  const childId = (parent.result as { child: string }).child;

  await page.goto(`./#/runs/${parentId}`);
  const child = page.locator(`[data-testid="run-child"][data-run="${childId}"]`);
  await expect(child).toBeVisible();
  await expect(child).toHaveAttribute("data-status", "done");
  await expect(child).toContainText("echo");
  await expect(child).toContainText("from spawn");

  await child.getByRole("link", { name: childId }).click();
  const started = page.getByTestId("run-parent");
  await expect(started).toContainText(parentId);
  await expect(started).toContainText("spawn");
  await expect(started).toContainText("depth 1");
  await expect(page.getByTestId("run-agent")).toHaveText("e2e");
  await expect(page.getByTestId("run-session")).toHaveText("orchestrated");   // a child is run by whoever ran its parent
});
