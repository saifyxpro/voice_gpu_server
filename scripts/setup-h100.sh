#!/usr/bin/env bash
# Generic H100 / GPU server setup (non-Lightning). Uses conda active env via --python.
#
# On Lightning AI Studio, use ./scripts/setup-lightning.sh instead.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

if [[ -n "${CONDA_DEFAULT_ENV:-}" ]] && [[ "${CONDA_DEFAULT_ENV}" == *cloudspace* ]]; then
  echo "Detected Lightning cloudspace — use ./scripts/setup-lightning.sh instead." >&2
  exit 1
fi

if [[ -z "${CONDA_DEFAULT_ENV:-}" && -z "${VIRTUAL_ENV:-}" ]]; then
  echo "Activate your GPU conda/venv first." >&2
  exit 1
fi

PY="$(which python)"
rm -rf .venv
echo "Using Python at ${PY}"

pip_install() {
  if command -v uv >/dev/null 2>&1; then
    uv pip install --python "${PY}" "$@"
  else
    pip install "$@"
  fi
}

if command -v uv >/dev/null 2>&1 && uv sync --help 2>&1 | grep -q -- '--active'; then
  uv sync --active
else
  pip_install -e .
fi

pip_install --force-reinstall \
  torch==2.6.0 torchvision==0.21.0 torchaudio==2.6.0 \
  --index-url https://download.pytorch.org/whl/cu124
pip_install "chatterbox-tts>=0.1.3"
pip_install "nemo_toolkit[asr] @ git+https://github.com/NVIDIA/NeMo.git"

"${PY}" -c "from chatterbox.tts_turbo import ChatterboxTurboTTS; print('chatterbox ok')"
"${PY}" -c "import nemo; print('nemo ok')"

echo "Start: python -m voice_gpu_server"
