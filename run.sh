#!/usr/bin/env bash
# Loads .env into the shell environment *before* starting Streamlit.
#
# This has to happen here, not inside app/config.py: Streamlit's own CLI
# bootstrap imports protobuf-based modules before the app's own code ever
# runs, which locks in the C++ protobuf implementation process-wide. By the
# time app/config.py's load_dotenv()/os.environ calls run, it's too late for
# PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION specifically -- it has to already be
# in the environment when the `streamlit` process starts.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

exec streamlit run app/main.py "$@"
