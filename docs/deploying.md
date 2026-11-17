# Where the catalog and the runs live

Every run happens on the machine that starts it. What `aip server` keeps is the catalog of
published procedures and the record of every run, in one graph. This page is the three ways to
set that up, in the order most people meet them: on your own machine, on your own machine with
Neo4j Browser looking in, and shared across teams.

| | Who starts what | Good for |
|---|---|---|
| [On your machine](#on-your-machine) | nothing: `aip` starts a server when it needs one | one person, a laptop, CI |
| [Explore the data with Cypher](#explore-the-data-with-cypher) | `relate serve`, then `aip server` | looking at the procedures and runs as a graph, in Neo4j Browser or from a driver |
| [Share Across Teams](#share-across-teams) | a Neo4j database, usually Aura, and one or more `aip server`s | one catalog and one record for many people |

The design behind all three is [`server-design.md`](server-design.md).

## On your machine

This is what the installer sets up, and there is nothing to run:

```bash
aip config server local      # the installer has done this already
aip list                     # the first command that needs a server starts one
```

The server listens on `http://127.0.0.1:8247`, stops when it has been idle for fifteen minutes,
and the next command starts it again. Its store is one file,
`~/.local/share/aip/server/store.rl`, kept by [Relate](https://relatedb.ai), an embedded graph
database that is installed with `aip`. `aip server --local --stop` stops it now.

**The server is the only program that can open that file while it runs.** Nothing else can read
it, not even read-only. To look at the runs you have `aip runs`, `aip audit` and the console
(`npx aip-console --server http://127.0.0.1:8247`). To look at them in Neo4j Browser, or from
any Bolt driver, use the next section.

## Explore the data with Cypher

The catalog and the runs are a graph, and Cypher is the way to ask it anything the built-in
audit queries do not. To have Neo4j Browser and the server on the same store at once, Relate
serves the file over Bolt and the server becomes one of its clients, as Browser is. It is the
same store file before and after, so nothing is copied or converted.

**1. Install the `relate` command.** It is a separate program from the `relate-db` library that
`aip` installs.

```bash
curl -sSfL https://relatedb.ai/install.sh | bash
relate --version
```

On Windows, download `relate-windows-amd64.exe` from the
[Relate releases](https://github.com/relatedb/relate/releases).

**2. Stop the server that has the file open.**

```bash
aip server --local --stop        # the on-demand local server; Ctrl-C a server you started yourself
```

**3. Serve the store over Bolt.** Pick a password; it is the one Browser and the server both use.

```bash
relate serve --database ~/.local/share/aip/server/store.rl --bolt 7687 --auth neo4j:<password>
```

Leave it running. It listens on this machine only (`127.0.0.1`).

**4. Start the server against it,** in a second terminal, and point the client at that server.

```bash
export NEO4J_PASSWORD=<password>
aip server --backend neo4j --uri bolt://127.0.0.1:7687 --user neo4j     # http://127.0.0.1:8000
aip config server http://127.0.0.1:8000                                 # a third terminal
aip list                                                                # the same catalog as before
```

The backend is called `neo4j` because Bolt is the protocol Neo4j speaks; the store is still your
Relate file. `GET /health` says `"backend": "neo4j"` for the same reason.

**5. Open Neo4j Browser.** Go to [browser.neo4j.io](https://browser.neo4j.io), choose
`neo4j://`, enter `127.0.0.1:7687`, user `neo4j` and your password. Any Bolt driver connects
the same way, to `bolt://127.0.0.1:7687`.

Then ask. Every procedure the store holds, with its steps:

```cypher
MATCH (p:Procedure)-[:HAS_STEP]->(s:Step)
RETURN p, s
```

[`language/queries.md`](language/queries.md) has the queries worth knowing: the control flow of
a procedure, where a key comes from, the runs of a procedure step by step, which routes fired
their confidence check. [`language/bundle.md`](language/bundle.md) is the schema.

**Whoever connects over Bolt can write as well as read.** There is one password and no
read-only user, so treat the address as the database itself and do not change the graph by
hand: the record is what an audit reads.

**To go back** to the server that needs nothing: stop both programs, then

```bash
aip config server local
```

Everything published or recorded in between is in the file, and the local server serves it.

What was checked: steps 2 to 4 and the way back were run on 2026-11-17 on one store with a
procedure published first (`relate` 1.0.1, `relate-db` 1.1.0), and the server's whole test suite
passes against a store served this way. A driver was connected over Bolt, and a wrong password
was refused. Step 5, the hosted Browser, follows Relate's own guide
([Connect Neo4j Browser](https://relatedb.ai/docs/guides/serve/bolt.md)) and was not run here.

## Share Across Teams

For one catalog and one record that many people use, the store is a database that everyone's
server can reach. `aip server` connects over Bolt to any Neo4j database, or to a Relate instance
served as above. The easiest to host is [Neo4j Aura](https://console.neo4j.io), because it is
fully managed: no machine to run, backups included.

**1. Create the database.** In the [Aura console](https://console.neo4j.io), create an instance
and download its credentials file when it is offered: the password is shown once. You need three
values from it: the URI (`neo4j+s://xxxxxxxx.databases.neo4j.io`), the user (`neo4j`) and the
password.

**2. Connect a server to it.**

```bash
export NEO4J_PASSWORD=<password>
aip server --backend neo4j --uri neo4j+s://xxxxxxxx.databases.neo4j.io --user neo4j
aip config server http://127.0.0.1:8000
aip list        # the four procedures aip ships, published on the store's first start
```

To keep the settings instead of typing them, `aip server --init` writes
`~/.config/aip/server.toml` with every setting commented; set `kind = "neo4j"`, `uri` and `user`
under `[backend]`, and keep the password in the environment or in a `.env` file beside where you
start the server.

In this arrangement the server is still on your machine and only the database is remote.
Everyone who does the same sees the same catalog and the same runs, and Neo4j Browser or Aura's
Query tab opens the same graph with no extra step.

### One server for everyone

Each person running their own server is the quick way, and it has costs: every laptop holds the
database password, which can change anything, and the record cannot say who made a run, because
a server on your own machine asks for no token. For a team that needs either, run one
`aip server` that everyone points at:

```bash
aip server --backend neo4j --uri neo4j+s://xxxxxxxx.databases.neo4j.io --user neo4j \
           --host 0.0.0.0 --no-localhost          # on a machine everyone can reach; tokens below
```

with the people named in its config file (`aip server --init`):

```toml
[tokens]            # one bearer token per person; the name is the `user` on their runs
zach = "..."
priya = "..."

[server]
read_token = "..."  # a token that can read and nothing else: the console for an auditor
```

and each person, once:

```bash
aip config server https://aip.example.com --token <their token>
```

What that buys:

- **The database password is in one place.** Clients hold a token for the server, not for the
  database.
- **The record says who.** Every run is recorded with the name of the token that made it; `aip
  runs --user zach` and the audit queries filter on it.
- **One console.** `npx aip-console --server https://aip.example.com`, with a token, shows the
  whole team's catalog and history.
- **One place to upgrade.**

What to know before relying on it:

- **A named token can do everything**, publishing included, and publishing decides what code
  other people's clients run. The read-only token is the only narrower one the config file
  offers today.
- **`aip server` serves plain HTTP.** Put it behind something that terminates TLS (a reverse
  proxy, a load balancer) before it leaves a private network, and keep `--host` on `127.0.0.1`
  until a token is set.
- **The server runs no procedure.** Runs still happen on each person's machine, with their
  files, their decision-model key and their credentials; the server is where they are published
  and recorded.

What was checked: a server on the Neo4j backend was started, listed and published to on
2026-11-17 against a local Neo4j, and the server's test suite runs over Neo4j as well as Relate.
An Aura instance, a server on a remote machine, and the console pointed at one were not run for
this page; that is milestone D3 of the 0.9 plan.
