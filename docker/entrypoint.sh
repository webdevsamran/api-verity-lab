#!/bin/sh
# One image, two jobs: the self-hosted server and the CLI.
#
# The image shipped with a `CMD` that started the server and no `ENTRYPOINT`,
# so the only documented way to use it was as a server. `docker run IMAGE
# apiverity breaking a.yaml b.yaml` did happen to work -- the console script is
# on PATH and Docker replaces `CMD` with whatever arguments follow the image --
# but nothing said so, nothing tested it, and the word `apiverity` had to be
# repeated after an image already named that.
#
# So the entrypoint dispatches: `serve` starts the server, anything else is a
# subcommand.
#
#   docker run -p 8090:8090 -v verity-data:/data IMAGE            # serve
#   docker run -v "$PWD:/work" IMAGE breaking old.yaml new.yaml   # the CLI
#   docker run IMAGE --help
#
# `set -eu` and not `pipefail`: this is `/bin/sh` in a slim image, and
# `pipefail` is a bashism that would make the script fail on the shell rather
# than on the command.
set -eu

case "${1:-serve}" in
    serve)
        exec python -c "import os
from apiverity.server import Store, create_app

# Origins are read from the environment and default to none. A server that
# answers every origin by default is a server whose operator never chose to --
# and every route here is authenticated, so '*' is refused outright.
origins = [o.strip() for o in os.environ.get('VERITY_CORS_ORIGINS', '').split(',') if o.strip()]
app = create_app(
    Store(os.environ.get('VERITY_DB', '/data/verity.db')),
    cors_origins=origins or None,
)
app.run(host='0.0.0.0', port=int(os.environ.get('VERITY_PORT', '8090')))"
        ;;
    sh|/bin/sh|bash)
        # An escape hatch for debugging a running image, and named explicitly
        # rather than reached by accident: `apiverity sh` is not a subcommand,
        # so without this it would fail with an argparse error that says
        # nothing about containers.
        shift
        exec /bin/sh "$@"
        ;;
    *)
        exec apiverity "$@"
        ;;
esac
