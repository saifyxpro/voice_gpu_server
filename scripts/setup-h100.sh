#!/usr/bin/env bash
# One-env H100 setup — installs everything into the ACTIVE conda/venv (no split .venv).
#
# Usage:
#   conda activate cloudspace
#   ./scripts/setup-h100.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

if [[ -z "${CONDA_DEFAULT_ENV:-}" && -z "${VIRTUAL_ENV:-}" ]]; then
  echo "Activate your GPU conda env first, e.g.: conda activate cloudspace" >&2
  exit 1
fi

PY="$(which python)"
PY_VER="$("${PY}" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
echo "Using Python ${PY_VER} at ${PY}"

case "${PY_VER}" in
  3.11|3.12|3.13) ;;
  *)
    echo "Python ${PY_VER} is not supported. Use 3.11, 3.12, or 3.13 (not 3.14)." >&2
    exit 1
    ;;
esac

# Avoid uv creating a separate .venv that diverges from conda
rm -rf .venv
echo "Removed .venv — installing into active environment only"

echo ""
echo "=== uv sync (active env) ==="
uv sync --active

echo ""
echo "=== CUDA PyTorch ==="
uv pip install --active torch torchaudio --index-url https://download.pytorch.org/whl/cu124

echo ""
echo "=== Chatterbox TTS ==="
uv pip install --active "chatterbox-tts>=0.1.3"

echo ""
echo "=== NeMo (Canary STT) ==="
uv pip install --active "nemo_toolkit[asr] @ git+https://github.com/NVIDIA/NeMo.git"

echo ""
echo "=== Verify imports ==="
uv run --active python -c "from chatterbox.tts_turbo import ChatterboxTurboTTS; print('chatterbox ok')"
uv run --active python -c "import nemo; print('nemo ok')"
uv run --active python -c "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available())"

cat <<EOF

✅ Setup complete in active env: ${CONDA_DEFAULT_ENV:-${VIRTUAL_ENV##*/}}

Start server:
  uv run --active voice-gpu-server

Run API tests:
  export VOICE_GPU_API_KEY=\$(grep '^VOICE_GPU_API_KEY=' .env | cut -d= -f2-)
  ./scripts/test-api.sh http://127.0.0.1:8765
EOF
