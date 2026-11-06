/** Project-local Pi tools. All operations pass through the bounded Python API.
 * This extension has no broker, arbitrary shell, SQL, or file-write tool.
 * To limit Pi itself to these tools, launch with --no-builtin-tools.
 */
import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { Type } from "@earendil-works/pi-ai";
import { defineTool, type ExtensionAPI } from "@earendil-works/pi-coding-agent";

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const date = Type.String({ pattern: "^\\d{4}-\\d{2}-\\d{2}$", description: "YYYY-MM-DD" });
const stockIds = Type.Array(Type.String({ pattern: "^[A-Za-z0-9]{1,16}$" }), { minItems: 1, maxItems: 10 });
const id = Type.String({ pattern: "^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$" });
const version = Type.String({ pattern: "^\\d+\\.\\d+\\.\\d+$" });
const researchConfig = Type.Object({
  name: id,
  variable: Type.Object({
    name: Type.Union([Type.Literal("turnover_rate"), Type.Literal("close"), Type.Literal("open"), Type.Literal("high"), Type.Literal("low"), Type.Literal("volume"), Type.Literal("amount")]),
    thresholds: Type.Array(Type.Number({ exclusiveMinimum: 0 }), { minItems: 1, maxItems: 40 }),
    unit: Type.Optional(Type.Literal("ratio")),
  }),
  forward_periods: Type.Array(Type.Integer({ minimum: 1, maximum: 180 }), { minItems: 1, maxItems: 40 }),
  date_range: Type.Object({ start: date, end: date }, { additionalProperties: false }),
  event_mode: Type.Optional(Type.Union([Type.Literal("daily"), Type.Literal("first_crossing")])),
  universe: Type.Optional(Type.Object({ mode: Type.Literal("observed_price_universe") }, { additionalProperties: false })),
  price: Type.Optional(Type.Object({ adjusted: Type.Literal(false) }, { additionalProperties: false })),
  exploratory: Type.Optional(Type.Literal(true)),
}, { additionalProperties: false });

async function invoke(tool: string, args: unknown, signal: AbortSignal): Promise<unknown> {
  return await new Promise((resolve, reject) => {
    const python = process.env.HK_QUANT_PYTHON || "python";
    const child = spawn(python, ["-m", "hk_quant.agent", "--processed-dir", "data/processed", "--registry-dir", "experiments"], {
      cwd: projectRoot,
      shell: false,
      env: { ...process.env, PYTHONPATH: path.join(projectRoot, "src") },
      stdio: ["pipe", "pipe", "pipe"],
    });
    let output = "";
    let settled = false;
    const done = (error?: Error, result?: unknown) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      signal.removeEventListener("abort", abort);
      if (error) reject(error);
      else resolve(result);
    };
    const abort = () => { child.kill(); done(new Error("Research tool cancelled")); };
    const timeout = setTimeout(() => { child.kill(); done(new Error("Research tool exceeded its time budget")); }, (tool.endsWith("workflow") ? 1_200_000 : 120_000));
    signal.addEventListener("abort", abort, { once: true });
    child.stdout.setEncoding("utf8");
    child.stdout.on("data", (chunk: string) => {
      output += chunk;
      if (output.length > 2_000_000) { child.kill(); done(new Error("Research response exceeds 2 MB")); }
    });
    child.stderr.resume(); // stderr can contain sensitive local paths; never return it to the model.
    child.on("error", (error) => done(error));
    child.on("close", () => {
      try { done(undefined, JSON.parse(output)); }
      catch { done(new Error("Research tool did not return a valid response")); }
    });
    child.stdin.end(JSON.stringify({ tool, arguments: args }));
  });
}

export default function (pi: ExtensionAPI) {
  function register(name: string, description: string, parameters: any) {
    pi.registerTool(defineTool({
      name: `hk_quant_${name}`,
      label: `HK Quant: ${name}`,
      description,
      parameters,
      async execute(_toolCallId, params, signal) {
        const result: any = await invoke(name, params, signal);
        return {
          content: [{ type: "text" as const, text: JSON.stringify(result) }],
          details: result,
          isError: result.ok === false,
        };
      },
    }));
  }
  const workflowSpec = Type.Object({
    name: id,
    stocks: Type.Array(Type.String({pattern:"^[0-9]{1,5}$"}), {minItems:1,maxItems:7}),
    start: date, end: date,
    score: Type.String({minLength:1,maxLength:100}),
    top_n: Type.Integer({minimum:1,maximum:7}),
    rebalance: Type.Integer({minimum:1,maximum:756}),
    filters: Type.Optional(Type.Array(Type.Object({field:Type.String(),op:Type.Union([Type.Literal(">"),Type.Literal(">="),Type.Literal("<"),Type.Literal("<="),Type.Literal("=="),Type.Literal("!=")]),value:Type.Number()},{additionalProperties:false}),{maxItems:20})),
    ascending: Type.Optional(Type.Boolean()),
    action_policy: Type.Optional(Type.Union([Type.Literal("strict"),Type.Literal("price_only")])),
    commission_rate: Type.Optional(Type.Number({minimum:0,exclusiveMaximum:1})),
    slippage_rate: Type.Optional(Type.Number({minimum:0,exclusiveMaximum:1})),
    initial_capital: Type.Optional(Type.Number({exclusiveMinimum:0})),
    warmup_days: Type.Optional(Type.Integer({minimum:1,maximum:3000})),
    universe: Type.Optional(Type.Union([Type.Literal("explicit"),Type.Literal("historical")])),
  },{additionalProperties:false});
  const workflowArgs = Type.Object({spec:workflowSpec,offline:Type.Optional(Type.Boolean()),refresh:Type.Optional(Type.Boolean())},{additionalProperties:false});
  register("plan_workflow", "Validate the user's explicit strategy and list required fields; no download or backtest.",workflowArgs);
  register("prepare_workflow", "Prepare required data with retries, coverage checks and conflict records; no trading.",workflowArgs);
  register("run_workflow", "Run an authorized strategy on a frozen snapshot with benchmark and exposure tracking; historical simulation only.",workflowArgs);
  register("get_data_coverage", "Read observed data coverage, missing fields, and content version before requesting research.", Type.Object({}, { additionalProperties: false }));
  register("get_market_data", "Read a bounded snapshot of canonical historical prices. amount is not turnover_rate.", Type.Object({ stock_ids: stockIds, start_date: date, end_date: date, limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 500 })) }, { additionalProperties: false }));
  register("plan_research", "Parse a turnover-rate research question conservatively. A NEEDS_INPUT response never runs the study.", Type.Object({ question: Type.String({ minLength: 1, maxLength: 2000 }), start_date: Type.Optional(date), end_date: Type.Optional(date), thresholds: Type.Optional(Type.Array(Type.Number(), { maxItems: 40 })), forward_periods: Type.Optional(Type.Array(Type.Integer({ minimum: 1, maximum: 180 }), { maxItems: 40 })) }, { additionalProperties: false }));
  register("run_research", "After checking coverage, run one deterministic bounded research config and register immutable artifacts; no strategy or order generated.", Type.Object({ config: researchConfig }, { additionalProperties: false }));
  register("get_research_result", "Read a registered research summary with checksum verification.", Type.Object({ experiment_id: id }, { additionalProperties: false }));
  register("get_experiment", "Read experiment metadata.", Type.Object({ experiment_id: id }, { additionalProperties: false }));
  register("compare_experiments", "Read deterministic differences between two to five registered experiments.", Type.Object({ experiment_ids: Type.Array(id, { minItems: 2, maxItems: 5 }) }, { additionalProperties: false }));
  register("validate_strategy", "Inspect and validate an immutable saved strategy version.", Type.Object({ strategy_id: id, version }, { additionalProperties: false }));
  register("generate_signals", "Evaluate existing strategy rules on a date and a bounded stock list; outputs signals, never orders.", Type.Object({ strategy_id: id, version, date, stock_ids: stockIds }, { additionalProperties: false }));
  register("run_risk_analysis", "Calculate descriptive historical risk for an explicit stock list and as-of date; registers result.", Type.Object({ stock_ids: stockIds, as_of_date: date, window: Type.Optional(Type.Integer({ minimum: 20, maximum: 756 })) }, { additionalProperties: false }));
  // Strategy creation, backtest and validation are intentionally omitted from
  // Pi's initial active tools; they remain available through the typed Python
  // protocol after a user has explicitly reviewed the proposed config.
}
