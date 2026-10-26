import {execFileSync} from 'node:child_process';
import path from 'node:path';
export default function setup() {
  const python = process.env.AUTHENTRA_TEST_PYTHON || path.resolve(process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python');
  execFileSync(python, ['tests/browser/prepare.py'], {stdio:'inherit'});
}
