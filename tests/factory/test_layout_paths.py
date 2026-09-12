"""Layout guard for the factory/ namespace reorg (hermetic, stdlib only).

Pins every moved default back to factory/ so the next move fails loudly
instead of silently orphaning resume state, packs, or keys:

- factory/.env location (core/env_loader, core/probe_keys)
- factory/packs + factory/fixtures dirs (lexicon default_pack/pool, registry _HERE)
- factory/*_progress.json resume defaults (lexicon progress paths)
"""

import os
import pathlib

FACTORY_DIR = pathlib.Path(__file__).resolve().parent.parent.parent / "factory"

from factory.core import registry as R
from factory.lexicon import awl_coverage as AC
from factory.lexicon import build_kaikki_index as BKI
from factory.lexicon import download_kaikki as DK
from factory.lexicon import phrase_judge as PJ
from factory.lexicon import phrase_pool as PP
from factory.lexicon import sample_lemmas as SL


def _inside_factory(path):
    path = pathlib.Path(os.path.normpath(str(path))).resolve()
    try:
        path.relative_to(FACTORY_DIR.resolve())
    except ValueError:
        raise AssertionError("%s is outside %s" % (path, FACTORY_DIR))
    # Must sit directly under factory/ (or a committed subdir like
    # packs/fixtures), never under a code package dir.
    for pkg in ("pipeline", "lexicon", "core", "archive"):
        if pkg in path.relative_to(FACTORY_DIR.resolve()).parts:
            raise AssertionError("%s leaks into package dir %s" % (path, pkg))
    return path


def test_factory_dir_exists():
    assert FACTORY_DIR.is_dir()


def test_env_paths_stay_in_factory():
    import factory.core.env_loader as EL
    import factory.core.probe_keys as PK

    el_env = pathlib.Path(EL.__file__).resolve().parent.parent / ".env"
    pk_env = pathlib.Path(PK.__file__).resolve().parent.parent / ".env"
    assert el_env == FACTORY_DIR / ".env"
    assert pk_env == FACTORY_DIR / ".env"


def test_registry_defaults_stay_in_factory():
    assert pathlib.Path(R._HERE).resolve() == FACTORY_DIR.resolve()


def test_lexicon_script_dirs_stay_in_factory():
    for mod in (SL, AC, PJ, PP, BKI):
        assert pathlib.Path(mod.script_dir()).resolve() == FACTORY_DIR.resolve()
    assert DK.script_dir().resolve() == FACTORY_DIR.resolve()


def test_pack_pool_progress_defaults_stay_in_factory():
    _inside_factory(SL.default_pack("en"))
    _inside_factory(SL.progress_path("en"))
    _inside_factory(AC.default_pool("en"))
    _inside_factory(AC.default_pack("en"))
    _inside_factory(PJ.default_phrases())
    _inside_factory(PJ.default_out())
    _inside_factory(PJ.default_progress())
    _inside_factory(PP.DEFAULT_OUT_DIR)
    _inside_factory(BKI.progress_path("en"))
    _inside_factory(DK.progress_path("en"))


def test_blind50_env_defaults_stay_put():
    """blind50 key files: factory/.env + repo tools/egress/.env."""
    import os as _os

    here = _os.path.dirname(
        _os.path.abspath(__import__(
            "factory.pipeline.blind50", fromlist=["x"]).__file__))
    factory_env = _os.path.normpath(_os.path.join(here, "..", ".env"))
    egress_env = _os.path.normpath(
        _os.path.join(here, "..", "..", "tools", "egress", ".env"))
    assert pathlib.Path(factory_env).resolve() == FACTORY_DIR / ".env"
    repo_root = FACTORY_DIR.parent
    assert pathlib.Path(egress_env).resolve() == \
        repo_root / "tools" / "egress" / ".env"


def test_archive_root_is_factory():
    """Archive ROOT triple-parent must equal factory/ (move detector)."""
    import factory.archive.v14_v16.run_v15_topics as _rt

    assert pathlib.Path(_rt.ROOT).resolve() == FACTORY_DIR.resolve()
