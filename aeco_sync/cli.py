"""Command-line editor and transaction coordinator."""

import argparse
import json
import sys
from pathlib import Path
from . import register_plugins


def main(argv=None):
    parser = argparse.ArgumentParser(prog="aeco-sync")
    parser.add_argument(
        "--stage", default="stage.usda", help="Session root (default: ./stage.usda)"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("model")
    init.add_argument("ifc")
    init.add_argument("--kind-import", action="store_true")
    init.add_argument("--host", default="ifc")
    init.add_argument("--host-module")
    init.add_argument("--directory")
    init.add_argument(
        "--policy",
        choices=("keepConnected", "disconnect", "refuse"),
        default="keepConnected",
    )
    sub.add_parser("status")
    apply_parser = sub.add_parser("apply")
    apply_parser.add_argument(
        "--host", default="ifc"
    )
    apply_parser.add_argument(
        "--policy", choices=("keepConnected", "disconnect", "refuse")
    )
    read = sub.add_parser("readback")
    read.add_argument("--host", required=True)
    read.add_argument(
        "ifc",
        nargs="?",
        help="IFC path, or foreground native path for Revit (otherwise AECO_REVIT_DOCUMENT)",
    )
    for command in (apply_parser, read):
        command.add_argument("--host-module", help="Explicit module:Class implementation")
        command.add_argument(
            "--validate-all",
            action="store_true",
            help="Validate the complete IFC, including EXPRESS rules",
        )
        command.add_argument(
            "--ids",
            type=Path,
            help="Validate the document against an IDS specification (requires ifctester)",
        )
    withdraw = sub.add_parser("withdraw")
    withdraw.add_argument("properties", nargs="*")
    edit = sub.add_parser("edit")
    edit.add_argument("prim")
    edit.add_argument("assignments", nargs="+")
    args = parser.parse_args(argv)
    try:
        register_plugins()
        from .stack import Session, create, PREFIX
        from . import edits, engine

        if args.command == "init":
            from .hosts.base import host_class
            cls = host_class(args.host, args.host_module)
            session = cls.initialize(args.model, args.ifc, args.directory,
                                     args.policy, kind_import=args.kind_import)
            result = {"stage": str(session.path), **session.status()}
        else:
            session = Session(args.stage)
            if args.command == "status":
                result = session.status()
            elif args.command == "edit":
                edits.author(session, args.prim, args.assignments)
                result = session.status()
            elif args.command == "withdraw":
                result = {
                    "withdrawn": edits.withdraw(session, args.properties),
                    **session.status(),
                }
            elif args.command == "apply":
                if args.policy:
                    session.root.customLayerData = {
                        **session.root.customLayerData,
                        PREFIX + "gapPolicy": args.policy,
                    }
                    session.root.Save()
                result = engine.apply(
                    session, args.host, validate_all=args.validate_all, ids=args.ids, host_module=args.host_module
                )
            else:
                result = engine.readback(
                    session,
                    args.host,
                    args.ifc,
                    validate_all=args.validate_all,
                    ids=args.ids,
                    host_module=args.host_module,
                )
        print(json.dumps(result, indent=2, default=str))
        return 0
    except Exception as exc:
        print(f"aeco-sync: {exc}", file=sys.stderr)
        return 1
