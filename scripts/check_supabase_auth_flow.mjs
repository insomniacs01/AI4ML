import fs from "node:fs";
import path from "node:path";

const repoRoot = process.cwd();
const envPath = path.join(repoRoot, "frontend", ".env.local");

function parseEnvFile(filePath) {
  const result = {};
  if (!fs.existsSync(filePath)) {
    return result;
  }

  for (const rawLine of fs.readFileSync(filePath, "utf8").split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#") || !line.includes("=")) {
      continue;
    }
    const [key, ...rest] = line.split("=");
    result[key.trim()] = rest.join("=").trim().replace(/^['"]|['"]$/g, "");
  }

  return result;
}

const env = parseEnvFile(envPath);
const supabaseUrl = process.env.VITE_SUPABASE_URL ?? env.VITE_SUPABASE_URL ?? "";
const supabaseKey = process.env.VITE_SUPABASE_PUBLISHABLE_KEY ?? env.VITE_SUPABASE_PUBLISHABLE_KEY ?? "";

if (!supabaseUrl || !supabaseKey) {
  console.error("Missing VITE_SUPABASE_URL or VITE_SUPABASE_PUBLISHABLE_KEY.");
  process.exit(1);
}

async function readAuthSettings() {
  const response = await fetch(`${supabaseUrl}/auth/v1/settings`, {
    headers: {
      apikey: supabaseKey,
      Authorization: `Bearer ${supabaseKey}`,
    },
  });

  if (!response.ok) {
    throw new Error(`Failed to read auth settings: ${response.status} ${await response.text()}`);
  }

  return response.json();
}

async function main() {
  const settings = await readAuthSettings();
  console.log(JSON.stringify({
    disable_signup: settings.disable_signup,
    mailer_autoconfirm: settings.mailer_autoconfirm,
    phone_autoconfirm: settings.phone_autoconfirm,
    email_provider_enabled: settings.external?.email ?? false,
  }, null, 2));
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
});
