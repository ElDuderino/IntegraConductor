"""`integra7` command-line interface.

With --json, exactly one JSON object is written to stdout (errors included) and
the exit status is nonzero on failure. Human diagnostics go to stderr.
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from typing import Any

from . import __version__, errors
from .config import SETTABLE_KEYS, is_wsl, load_config, update_config_file
from .errors import EXIT_FAILURE, EXIT_OK, Integra7Error, usage_error
from .midi import wsl_interop
from .midi.backend import BACKENDS, MidiBackend
from .models import KINDS, error_result, ok_result
from .services import device, expansions, fx, parts, patches, play, studio_sets
from .services.core import AppContext

EPILOG = """examples:
  integra7 patches import                       build the catalog from bundled data
  integra7 patches search "fretless bass" --kind tone --limit 5 --json
  integra7 part select --part 2 --patch-id sn-a-preset-0001 --dry-run --json
  integra7 part select --part 1 --patch "Full Grand 1" --json
  integra7 studio-set select 1 --dry-run --json
  integra7 doctor --json

Patch IDs (e.g. sn-a-preset-0001) are unambiguous; names are accepted only when
they identify exactly one patch. Use --backend mock to work without hardware."""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):  # argparse would print usage and exit(2)
        raise usage_error(errors.INVALID_ARGUMENT, f"{self.prog}: {message}")


def _int_auto(text: str) -> int:
    return int(text, 0)


def _common() -> argparse.ArgumentParser:
    """Options accepted before or after any subcommand."""
    s = argparse.SUPPRESS
    p = argparse.ArgumentParser(add_help=False)
    g = p.add_argument_group("global options")
    g.add_argument("--json", action="store_true", default=s, help="emit one JSON object on stdout")
    g.add_argument("--config", default=s, metavar="PATH", help="config file (TOML)")
    g.add_argument("--backend", default=s, choices=BACKENDS, help="MIDI backend")
    g.add_argument("--db", dest="db_path", default=s, metavar="PATH", help="patch catalog path")
    g.add_argument("--performance-port", default=s, metavar="NAME")
    g.add_argument("--control-port", default=s, metavar="NAME")
    g.add_argument("--input-port", default=s, metavar="NAME")
    g.add_argument("--device-id", default=s, type=_int_auto, metavar="N",
                   help="SysEx device ID on the wire, e.g. 0x10 (shown as 17 on the unit)")
    return p


def build_parser() -> argparse.ArgumentParser:
    common = _common()

    def leaf(sub, name: str, handler, help_: str, **kw) -> argparse.ArgumentParser:
        p = sub.add_parser(name, parents=[common], help=help_, description=help_, **kw)
        p.set_defaults(handler=handler)
        return p

    def group(sub, name: str, help_: str):
        p = sub.add_parser(name, parents=[common], help=help_, description=help_)
        p.set_defaults(handler=lambda ctx, a, _p=p: _need_subcommand(_p))
        return p, p.add_subparsers(dest=f"{name}_command", metavar="COMMAND")

    root = _Parser(
        prog="integra7",
        parents=[common],
        description="Deterministic, agent-friendly control of the Roland INTEGRA-7.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    root.add_argument("--version", action="version", version=f"integra7 {__version__}")
    root.set_defaults(handler=lambda ctx, a: _need_subcommand(root))
    sub = root.add_subparsers(dest="command", metavar="COMMAND")

    p = leaf(sub, "doctor", _doctor, "diagnose interop, adapter, ports and catalog")
    p.add_argument("--write-config", action="store_true",
                   help="save the discovered Windows Python path to the config file")
    p.add_argument("--strict", action="store_true",
                   help="exit nonzero unless ready for hardware")
    leaf(sub, "ports", lambda c, a: device.list_ports(c), "list MIDI ports seen by the backend")
    leaf(sub, "capabilities", lambda c, a: device.capabilities(c),
         "describe supported operations and result semantics")

    # patches
    _, ps = group(sub, "patches", "patch catalog: import, search, show, audit, export")
    p = leaf(ps, "import", lambda c, a: patches.import_catalog(c, _local_path(a.source), a.compare),
             "build the SQLite catalog (bundled sources by default)")
    p.add_argument("source", nargs="?", help="Cubase patch script (default: bundled full list)")
    p.add_argument("--compare", action="append", metavar="FILE",
                   help="additional script to cross-check (repeatable)")
    p = leaf(ps, "search", _search, "search patches by name, tokens and filters")
    p.add_argument("query", nargs="?", default="")
    p.add_argument("--kind", choices=KINDS)
    p.add_argument("--engine", help="SN-A, SN-S, SN-D, PCM-S or PCM-D")
    p.add_argument("--category", help="substring of the category, e.g. 'Electric Piano'")
    p.add_argument("--expansion", help="none, any, or a name such as SRX-06 / ExSN1 / ExPCM")
    p.add_argument("--bank", help="substring of the Roland bank name")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--no-fuzzy", action="store_true", help="disable fuzzy token matching")
    p = leaf(ps, "show", lambda c, a: patches.show_patch(c, a.patch_id),
             "show one patch with provenance")
    p.add_argument("patch_id")
    leaf(ps, "audit", lambda c, a: patches.audit_catalog(c),
         "counts, duplicates, conflicts and coverage vs Roland's bank table")
    p = leaf(ps, "export", lambda c, a: patches.export_catalog(c, _local_path(a.output)),
             "export the normalized catalog as JSON")
    p.add_argument("--format", choices=["json"], default="json")
    p.add_argument("--output", metavar="PATH", help="file to write (default: stdout)")

    # part
    _, pt = group(sub, "part", "part operations: channels, select, audition, show")
    ch = leaf(pt, "channels", _channels, "show the part -> MIDI channel map")
    ch.add_argument("--from-device", action="store_true",
                    help="read receive channels from the unit (documented RQ1)")
    ch.add_argument("--save", action="store_true",
                    help="with --from-device: store the observed map in config")
    chs = ch.add_subparsers(dest="channels_command", metavar="COMMAND")
    p = leaf(chs, "set", lambda c, a: parts.set_channel(c, a.part, a.channel),
             "set the local mapping for one part (sends nothing)")
    p.add_argument("--part", type=int, required=True)
    p.add_argument("--channel", type=int, required=True)
    p = leaf(pt, "select", _select, "select a tone or drum kit on a part")
    p.add_argument("--part", type=int, required=True, help="part number 1-16")
    which = p.add_mutually_exclusive_group(required=True)
    which.add_argument("--patch-id", help="catalog ID (unambiguous)")
    which.add_argument("--patch", metavar="NAME", help="name; must identify exactly one patch")
    p.add_argument("--dry-run", action="store_true", default=None,
                   help="show what would be sent; send nothing")
    p.add_argument("--no-verify", action="store_true", help="skip SysEx readback")
    p = leaf(pt, "audition", _audition, "play one short note on a part")
    p.add_argument("--part", type=int, required=True)
    p.add_argument("--patch-id", help="select this patch first")
    p.add_argument("--note", type=int, default=60)
    p.add_argument("--velocity", type=int, default=90)
    p.add_argument("--duration-ms", type=int, default=800)
    p.add_argument("--dry-run", action="store_true", default=None)
    p = leaf(pt, "show", lambda c, a: parts.show_part(c, a.part),
             "read a part's channel and current tone from the unit")
    p.add_argument("--part", type=int, required=True)

    p = leaf(sub, "play", _play, "play a short multi-part score (JSON) once")
    p.add_argument("score", help="score file; see examples/ and services/play.py")
    p.add_argument("--tempo", type=float, help="override the score's tempo (BPM)")
    p.add_argument("--loop", type=int, default=1, metavar="N", help="play it N times in a row")
    p.add_argument("--keep-patch", metavar="N[,N...]",
                   help="do not re-select the score's patch on these parts (keep what is loaded)")
    p.add_argument("--keep-fx", action="store_true",
                   help="do not apply the score's effect settings (keep what is set on the unit)")
    p.add_argument("--dump-events", metavar="PATH",
                   help="write every MIDI event that is (or would be) sent to a JSON file")
    p.add_argument("--parts", metavar="N[,N...]",
                   help="play only these parts of the score, e.g. --parts 10 to solo the drums")
    p.add_argument("--dry-run", action="store_true", default=None)

    # fx
    _, fxp = group(sub, "fx", "Studio Set effects: reverb, chorus, surround room, EQ, sends")
    leaf(fxp, "list", lambda c, a: fx.describe(), "list settable effect parameters and ranges")
    p = leaf(fxp, "show", lambda c, a: fx.show(c, a.part), "read current effect settings")
    p.add_argument("--part", type=int, action="append", help="limit to these parts (repeatable)")
    p = leaf(fxp, "set", lambda c, a: fx.apply(c, fx.parse_assignments(a.settings),
                                               dry_run=a.dry_run),
             "set parameters, e.g. reverb.type=room2 part.1.reverb_send=40")
    p.add_argument("settings", nargs="+", metavar="PATH=VALUE")
    p.add_argument("--dry-run", action="store_true", default=None)

    # studio-set
    _, ss = group(sub, "studio-set", "Studio Set operations (affect all 16 parts)")
    leaf(ss, "list", lambda c, a: studio_sets.list_studio_sets(c), "list factory Studio Set names")
    p = leaf(ss, "select", _studio_select, "recall a Studio Set by number (1-64)")
    p.add_argument("number", type=int)
    p.add_argument("--dry-run", action="store_true", default=None)
    p.add_argument("--yes", action="store_true", help="confirm replacing all part settings")
    p.add_argument("--no-verify", action="store_true")

    # device
    _, dv = group(sub, "device", "read-only device queries over documented SysEx")
    leaf(dv, "identify", lambda c, a: device.identify(c), "send an Identity Request")
    p = leaf(dv, "state", lambda c, a: device.device_state(c, not a.no_parts),
             "read sound mode, Studio Set, control channel and parts")
    p.add_argument("--no-parts", action="store_true")

    # expansions
    _, ex = group(sub, "expansions", "expansion state (declared, never device-verified)")
    leaf(ex, "status", lambda c, a: expansions.status(c), "show declared/unknown expansion state")
    p = leaf(ex, "declare", lambda c, a: expansions.declare(c, a.names, a.unknown),
             "record which expansions you have loaded on the unit")
    p.add_argument("names", nargs="*", help="e.g. SRX-06 ExSN1 (or ExPCM alone)")
    p.add_argument("--unknown", action="store_true", help="forget the declared state")
    p = leaf(ex, "plan", lambda c, a: ok_result(expansions.plan(a.names)),
             "check whether expansions fit the four slots together")
    p.add_argument("names", nargs="+")

    # config
    _, cf = group(sub, "config", "show or change configuration")
    leaf(cf, "show", _config_show, "show effective configuration and where values come from")
    leaf(cf, "path", lambda c, a: ok_result({"config_path": c.config.path}), "print config path")
    p = leaf(cf, "set", _config_set, "persist one setting")
    p.add_argument("key", choices=SETTABLE_KEYS, metavar="KEY")
    p.add_argument("value")
    return root


def _need_subcommand(parser: argparse.ArgumentParser):
    raise usage_error(
        errors.INVALID_ARGUMENT,
        f"{parser.prog}: a subcommand is required",
        hint=f"Run `{parser.prog} --help`.",
    )


def _doctor(ctx: AppContext, a) -> dict[str, Any]:
    result = device.doctor(ctx, write_config=a.write_config)
    if a.strict and not result["data"]["ready_for_hardware"]:
        result["_exit_code"] = EXIT_FAILURE
    return result


def _search(ctx: AppContext, a) -> dict[str, Any]:
    return patches.search_patches(
        ctx, a.query, kind=a.kind, engine=a.engine, category=a.category,
        expansion=a.expansion, bank=a.bank, limit=a.limit, fuzzy=not a.no_fuzzy,
    )


def _channels(ctx: AppContext, a) -> dict[str, Any]:
    if a.from_device:
        return parts.channel_map_from_device(ctx, save=a.save)
    if a.save:
        raise usage_error(errors.INVALID_ARGUMENT, "--save requires --from-device")
    return parts.channel_map(ctx)


def _select(ctx: AppContext, a) -> dict[str, Any]:
    return parts.select_patch(
        ctx, a.part, patch_id=a.patch_id, name=a.patch, dry_run=a.dry_run,
        verify=False if a.no_verify else None,
    )


def _audition(ctx: AppContext, a) -> dict[str, Any]:
    return parts.audition(
        ctx, a.part, patch_id=a.patch_id, note=a.note, velocity=a.velocity,
        duration_ms=a.duration_ms, dry_run=a.dry_run,
    )


def _local_path(path: str | None) -> str | None:
    """Accept Windows-style paths (C:\\x or C:/x) when running inside WSL."""
    if path and is_wsl() and wsl_interop.is_windows_path(path):
        return wsl_interop.to_wsl_path(path.replace("/", "\\"))
    return path


def _play(ctx: AppContext, a) -> dict[str, Any]:
    score = play.load_score(_local_path(a.score) or a.score)
    def numbers(text: str | None, flag: str) -> list[int] | None:
        try:
            return [int(x) for x in text.split(",")] if text else None
        except ValueError:
            raise usage_error(
                errors.INVALID_ARGUMENT, f"{flag} must be numbers: {text!r}"
            ) from None

    return play.play_score(
        ctx, score, dry_run=a.dry_run, tempo_bpm=a.tempo, loops=a.loop,
        only_parts=numbers(a.parts, "--parts"), keep_patch=numbers(a.keep_patch, "--keep-patch"),
        dump_events=_local_path(a.dump_events), keep_fx=a.keep_fx,
    )


def _studio_select(ctx: AppContext, a) -> dict[str, Any]:
    return studio_sets.select_studio_set(
        ctx, a.number, dry_run=a.dry_run, confirmed=a.yes,
        verify=False if a.no_verify else None,
    )


def _config_show(ctx: AppContext, a) -> dict[str, Any]:
    return ok_result(
        {
            "config_path": ctx.config.path,
            "db_path": str(ctx.config.resolved_db_path()),
            "precedence": "CLI flags > INTEGRA7_* environment > config file > defaults",
            "values": ctx.config.to_dict(),
            "origins": ctx.config.origins,
        }
    )


def _config_set(ctx: AppContext, a) -> dict[str, Any]:
    update_config_file(ctx.config.path, {a.key: a.value})
    return ok_result({"config_path": ctx.config.path, "key": a.key, "value": a.value})


# ---------------------------------------------------------------- rendering

def _fmt(value: Any, indent: int = 0) -> list[str]:
    pad = "  " * indent
    if isinstance(value, dict):
        lines = []
        for k, v in value.items():
            if isinstance(v, (dict, list)) and v:
                lines.append(f"{pad}{k}:")
                lines += _fmt(v, indent + 1)
            else:
                lines.append(f"{pad}{k}: {_scalar(v)}")
        return lines
    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, dict):
                lines.append(f"{pad}- " + ", ".join(f"{k}={_scalar(v)}" for k, v in item.items()))
            else:
                lines.append(f"{pad}- {_scalar(item)}")
        return lines
    return [f"{pad}{_scalar(value)}"]


def _scalar(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def render_human(result: dict[str, Any]) -> str:
    lines: list[str] = []
    if not result.get("ok"):
        err = result["error"]
        lines.append(f"error [{err['code']}]: {err['message']}")
        if err.get("hint"):
            lines.append(f"hint: {err['hint']}")
        for cand in (err.get("details") or {}).get("candidates") or []:
            if isinstance(cand, dict):
                lines.append(f"  {cand.get('id', ''):<24} {cand.get('name', '')}")
        if result.get("verification_status"):
            lines.append(f"status: {result['verification_status']}")
        return "\n".join(lines)

    data = result.get("data")
    if isinstance(data, dict) and isinstance(data.get("results"), list):
        lines.append(f"{data['returned']} of {data['total_matches']} matches")
        for r in data["results"]:
            lines.append(
                f"{r['id']:<22} {r['name']:<18} {r['kind']:<10} {(r['category'] or '-'):<20} "
                f"MSB {r['bank_msb']:>3} LSB {r['bank_lsb']:>3} PC {r['display_pc']:>3}  "
                f"{r['expansion_required'] or ''}"
            )
    elif isinstance(data, dict) and isinstance(data.get("checks"), list):
        for c in data["checks"]:
            lines.append(f"[{c['status']:<4}] {c['name']}: {c['detail']}")
            if c.get("hint"):
                lines.append(f"       hint: {c['hint']}")
        lines.append(f"ready_for_offline_use: {data['ready_for_offline_use']}")
        lines.append(f"ready_for_hardware: {data['ready_for_hardware']}")
        lines.append(data["note"])
    else:
        lines += _fmt(data)
    if result.get("verification_status"):
        lines.append(f"status: {result['verification_status']} (backend: {result.get('backend')})")
    for w in result.get("warnings") or []:
        lines.append(f"warning: {w}")
    return "\n".join(lines)


def run(argv: list[str], backend: MidiBackend | None = None) -> tuple[int, dict[str, Any]]:
    """Execute a command line and return (exit_code, result envelope)."""
    ctx: AppContext | None = None
    try:
        args = build_parser().parse_args(argv)
        overrides = {
            k: getattr(args, k)
            for k in ("backend", "db_path", "performance_port", "control_port", "input_port",
                      "device_id")
            if hasattr(args, k)
        }
        ctx = AppContext(load_config(getattr(args, "config", None), overrides), backend)
        result = args.handler(ctx, args)
        return result.pop("_exit_code", EXIT_OK), result
    except Integra7Error as exc:
        return exc.exit_code, error_result(
            exc.to_dict(),
            backend=ctx.backend_name if ctx and exc.verification_status else None,
            verification_status=exc.verification_status,
        )
    except Exception as exc:  # unexpected: still honor the JSON contract
        traceback.print_exc(file=sys.stderr)
        return EXIT_FAILURE, error_result(
            {"code": errors.INTERNAL_ERROR, "message": f"{type(exc).__name__}: {exc}"}
        )
    finally:
        if ctx is not None:
            ctx.close()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    want_json = "--json" in argv
    try:
        code, result = run(argv)
    except SystemExit as exc:  # --help / --version
        return int(exc.code or 0)
    if want_json:
        sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    else:
        text = render_human(result)
        (sys.stdout if result.get("ok") else sys.stderr).write(text + "\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
