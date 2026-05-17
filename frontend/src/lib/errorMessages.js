const DEFAULT_ERROR_LIMIT = 240;
const QUOTA_ERROR_LIMIT = 360;

const RAW_RUNTIME_MARKERS = [
  "request options",
  "json_data",
  "idempotency_key",
  "x-stainless",
  "/chat/completions",
  "traceback",
  "return code:",
  "mlzero run failed",
  "[autogluon.assistant",
  "autogluon.assistant.",
  "\\mlzero_runs\\",
  "/mlzero_runs/",
  "\\storage\\mlzero_runs\\",
  "/storage/mlzero_runs/",
  "logs.txt tail",
  "info_logs.txt tail",
  "detail_logs.txt tail",
  "debugging_logs.txt",
  "captured stdout tail",
  "captured stderr",
  "wire_api=chat_completions",
  "tutorial retrieval is disabled",
  "install faiss-cpu",
];

function stringifyUnknown(value) {
  if (value == null) return "";
  if (value instanceof Error) return value.message || String(value);
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function pickPayloadMessage(payload) {
  if (!payload || typeof payload !== "object") return "";
  const candidates = [payload.detail, payload.message, payload.error, payload.reason];
  for (const candidate of candidates) {
    if (candidate == null) continue;
    if (typeof candidate === "string" && candidate.trim()) return candidate;
    if (typeof candidate === "object") return stringifyUnknown(candidate);
    return String(candidate);
  }
  return "";
}

function tryParseJsonMessage(value) {
  const text = String(value ?? "").trim();
  if (!text) return "";
  const candidates = [text];
  const objectStart = text.indexOf("{");
  if (objectStart > 0) candidates.push(text.slice(objectStart));
  for (const candidate of candidates) {
    if (!candidate.startsWith("{") && !candidate.startsWith("[")) continue;
    try {
      const parsed = JSON.parse(candidate);
      const picked = pickPayloadMessage(parsed);
      if (picked) return picked;
    } catch {
      // Keep the original text when it is not valid JSON.
    }
  }
  return text;
}

function unwrapServerMessage(value) {
  let text = stringifyUnknown(value).trim();
  for (let index = 0; index < 3; index += 1) {
    const next = tryParseJsonMessage(text).trim();
    if (!next || next === text) return text;
    text = next;
  }
  return text;
}

export function compactDisplayText(value, maxLength = DEFAULT_ERROR_LIMIT) {
  const text = stringifyUnknown(value).replace(/\s+/g, " ").trim();
  if (!text) return "";
  if (text.length <= maxLength) return text;
  return `${text.slice(0, Math.max(maxLength - 3, 0))}...`;
}

export function looksLikeRawRuntimeText(value) {
  const text = stringifyUnknown(value).toLowerCase();
  if (!text) return false;
  if (RAW_RUNTIME_MARKERS.some((marker) => text.includes(marker))) return true;
  if (/^[a-z]:\\/.test(text) && text.length > 80) return true;
  return text.length > 420 && (
    text.includes(" brief ")
    || text.includes(" info ")
    || text.includes(" warning ")
    || text.includes("autogluon")
    || text.includes("mlzero")
  );
}

export function formatErrorMessage(error, options = {}) {
  const rawText = unwrapServerMessage(error);
  if (!rawText) return "收到未知错误。";

  const lowered = rawText.toLowerCase();
  if (lowered.includes("agent 诊断")) {
    return compactDisplayText(rawText.replace(/agent 诊断/gi, "诊断结论"), options.maxLength ?? DEFAULT_ERROR_LIMIT);
  }
  if (looksLikeRawRuntimeText(rawText)) {
    if (lowered.includes("return code: 130")) {
      return "自动建模被外部中断，系统已生成诊断并保留报错文件；请在任务详情或运行详情查看。";
    }
    return "自动建模失败，系统已生成诊断并保留报错文件；请在任务详情或运行详情查看。";
  }

  if (lowered.includes("invalid login credentials")) return "邮箱或密码不正确。";
  if (lowered.includes("user already registered")) return "这个邮箱已经注册过了，可以直接登录。";
  if (lowered.includes("invite code not found")) return "没有找到对应的邀请码。";
  if (lowered.includes("team name is required")) return "请先填写团队名称。";
  if (lowered.includes("dataset has not been uploaded")) return "请先上传 CSV 数据集。";
  if (lowered.includes("only csv uploads are supported")) return "目前只支持 CSV 文件。";
  if (lowered.includes("task not found")) return "没有找到对应任务。";
  if (lowered.includes("connector not found")) return "没有找到对应 AI 服务。";
  if (lowered.includes("x-team-id header is required")) return "请先选择团队。";
  if (lowered.includes("you do not have access to the requested team")) return "你没有当前团队的访问权限。";
  if (lowered.includes("membership in the requested team is not active")) return "你在当前团队中的成员状态不是 active，暂时不能继续操作。";
  if (lowered.includes("missing supabase bearer token")) return "登录状态失效，请重新登录。";
  if (lowered.includes("requires a team admin role")) return "当前操作需要团队管理员权限。";
  if (lowered.includes("requires the team owner role")) return "当前操作需要团队所有者权限。";
  if (lowered.includes("only the current team owner can transfer ownership")) return "只有当前团队所有者可以转移所有权。";
  if (lowered.includes("team_owner must be assigned through the ownership transfer endpoint")) return "团队所有者只能通过所有权转移入口变更。";
  if (lowered.includes("team_owner cannot demote themselves")) return "团队所有者不能在成员表里降级自己，请使用所有权转移。";
  if (lowered.includes("requires a developer or team admin role")) return "当前操作需要开发成员或团队管理员权限。";
  if (lowered.includes("connector storage request")) return "AI 设置保存失败，请检查当前团队权限。";
  if (lowered.includes("governance request")) return "团队设置保存失败，请检查当前团队权限。";
  if (lowered.includes("waiting for human collaboration")) return "当前任务正在等待人工复核，请先处理复核请求或恢复任务。";
  if (lowered.includes("open human collaboration requests")) return "当前任务还有未处理的复核请求，请先处理。";
  if (lowered.includes("still in progress")) return "当前任务仍在运行中，暂时不能创建复核请求。";
  if (lowered.includes("quota")) return compactDisplayText(rawText, options.maxLength ?? QUOTA_ERROR_LIMIT);
  return compactDisplayText(rawText, options.maxLength ?? DEFAULT_ERROR_LIMIT);
}
