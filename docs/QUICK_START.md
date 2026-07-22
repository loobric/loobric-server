# Quick Start

> **Just want to kick the tires?** You don't have to run a server. Point the
> Python client at the free hosted sandbox and explore in two minutes — see
> [loobric-cli/docs/SANDBOX.md](https://github.com/loobric/loobric-cli/blob/master/docs/SANDBOX.md)
> (`pip install loobric-cli`, then run the `quickstart.sh` seed script against
> `https://api.loobric.com`). The steps below are for running your own server.

Loobric Server is brand new and not yet ready for production use.  If you're looking for a production ready solution, you will have to wait a bit.  If you're a curious developer or risk tolerant user, you can try it out by running it yourself.

1. Clone the repository

```
git clone https://github.com/loobric/loobric-server.git
```

2. Activate the virtual environment and install dependencies

```
cd loobric-server
uv venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
uv pip install -e ".[dev]"
```

3. Run the server

```
uvicorn loobric_server.main:app --reload
```

4. Create the admin user.

The first user created will automatically be the admin user.
You can create a user account with the command line utility.

```
  loobric --base-url http://127.0.0.1:8000 register admin@example.com
```

5. Login as the admin user

```
  loobric --base-url http://127.0.0.1:8000 login admin@example.com
```

Create an access token

```
  loobric create-key "Backup Script" \
    --scopes "read" --tags "backup production" --expires-at "2027-12-31T23:59:59Z"
```

6. Record the token

The previous command will echo the token back to the console in clear text. Only the token hash is stored in the database so the actual token can not be recovered.  Write it down or store it securely.

7. Use the token in one of the clients like [loobric-freecad](https://github.com/loobric/loobric-freecad)

## Next steps

Once a client is reporting tools, you review and bind them with `loobric`. See
the [CLI reference and walkthrough](https://github.com/loobric/loobric-cli/blob/master/docs/CLI.md) for every command and a worked
example from touch-off to a bound tool.