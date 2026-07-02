#!/usr/bin/env bash
# Fix torch / torchvision / torchaudio version mismatch (torchvision::nms error).
# Run inside: conda activate cloudspace
set -euo pipefail
PY="$(which python)"
echo "Reinstalling matched PyTorch stack for ${PY}..."

pip_install() {
  if command -v uv >/dev/null 2>&1; then
    uv pip install --python "${PY}" "$@"
  else
    pip install "$@"
  fi
}

pip_install --force-reinstall \
  torch==2.6.0 torchvision==0.21.0 torchaudio==2.6.0 \
  --index-url https://download.pytorch.org/whl/cu124

"${PY}" -c "import torch, torchvision; print('torch', torch.__version__); print('torchvision', torchvision.__version__); print('cuda', torch.cuda.is_available())"
echo "✅ PyTorch stack OK"
