#!/usr/bin/env fish
# Fish-native entrypoint; operational logic is Python stdlib, no shell evaluation.
set -l root (path resolve (path dirname (status filename))/..)
if not command -sq python3
    echo 'ERRO: python3 precisa estar instalado no host.' >&2
    exit 1
end
if not command -sq docker
    echo 'ERRO: Docker Engine e o plugin Docker Compose precisam estar instalados.' >&2
    exit 1
end
python3 "$root/scripts/deploy.py" $argv
exit $status
