import { execFile } from 'node:child_process';
import { stat } from 'node:fs/promises';
import path from 'node:path';

import { ai4mlDataRoot } from './config.js';

const dialogTimeoutMs = 10 * 60 * 1000;

export async function selectNativeDataPath(mode) {
  if (process.platform !== 'win32') {
    throw new Error('当前只支持在 Windows 上打开本机文件选择窗口。');
  }

  const normalizedMode = mode === 'directory' ? 'directory' : 'file';
  const initialDirectory = await resolveInitialDirectory();
  const script = normalizedMode === 'directory'
    ? buildDirectoryDialogScript(initialDirectory)
    : buildFileDialogScript(initialDirectory);
  const stdout = await runPowerShellDialog(script);
  const selectedPath = stdout.trim();

  if (!selectedPath) {
    return {
      cancelled: true
    };
  }

  const stats = await stat(selectedPath);

  return {
    cancelled: false,
    path: path.resolve(selectedPath),
    type: stats.isDirectory() ? 'directory' : 'file',
    size: stats.isFile() ? stats.size : undefined,
    modifiedAt: stats.mtime.toISOString()
  };
}

async function resolveInitialDirectory() {
  try {
    const stats = await stat(ai4mlDataRoot);
    if (stats.isDirectory()) {
      return path.resolve(ai4mlDataRoot);
    }
  } catch {
    // Fall back to the current project directory when the configured data root is unavailable.
  }

  return process.cwd();
}

function buildFileDialogScript(initialDirectory) {
  return `
Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.OpenFileDialog
$dialog.Title = '选择数据文件'
$dialog.InitialDirectory = ${quotePowerShellString(initialDirectory)}
$dialog.Filter = '所有文件 (*.*)|*.*'
$dialog.Multiselect = $false
$dialog.CheckFileExists = $true
$dialog.CheckPathExists = $true
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
  [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
  [Console]::Out.WriteLine($dialog.FileName)
}
`;
}

function buildDirectoryDialogScript(initialDirectory) {
  return `
Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = '选择数据文件夹'
$dialog.SelectedPath = ${quotePowerShellString(initialDirectory)}
$dialog.ShowNewFolderButton = $false
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
  [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
  [Console]::Out.WriteLine($dialog.SelectedPath)
}
`;
}

function runPowerShellDialog(script) {
  return new Promise((resolve, reject) => {
    execFile(
      'powershell.exe',
      [
        '-NoProfile',
        '-ExecutionPolicy',
        'Bypass',
        '-STA',
        '-Command',
        script
      ],
      {
        encoding: 'utf8',
        timeout: dialogTimeoutMs,
        windowsHide: false
      },
      (error, stdout, stderr) => {
        if (error) {
          reject(new Error(stderr.trim() || error.message));
          return;
        }

        resolve(stdout || '');
      }
    );
  });
}

function quotePowerShellString(value) {
  return `'${String(value).replace(/'/g, "''")}'`;
}
