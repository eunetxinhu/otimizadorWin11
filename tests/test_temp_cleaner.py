import os
import threading
import time

import pytest

from services.temp_cleaner import CleanupCategory, TempCleanerService, build_default_categories

DAY = 24 * 3600


class FakeRecycleBin:
    def __init__(self, size=0, items=0, empty_ok=True):
        self.size, self.items, self.empty_ok = size, items, empty_ok
        self.emptied = False

    def available(self):
        return True

    def query(self):
        return (self.size, self.items)

    def empty(self):
        if self.empty_ok:
            self.emptied = True
            self.size = self.items = 0
        return self.empty_ok


def symlink_or_skip(target, link, is_dir=False):
    try:
        os.symlink(target, link, target_is_directory=is_dir)
    except (OSError, NotImplementedError) as exc:  # Windows sem privilégio de criar symlink
        pytest.skip(f"symlink indisponível: {exc}")


def write(path, size=10, age_days=None, now=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    if age_days is not None:
        ts = now - age_days * DAY
        os.utime(path, (ts, ts))
    return path


@pytest.fixture
def now():
    # "Agora" dois dias no futuro: todo arquivo criado no teste parece ter 2 dias.
    # (No Linux não dá para envelhecer o ctime, então movemos o relógio.)
    return time.time() + 2 * DAY


def service(categories, now, **kw):
    kw.setdefault("recycle_bin", FakeRecycleBin())
    return TempCleanerService(categories=categories, clock=lambda: now, **kw)


def temp_category(folder, **kw):
    return CleanupCategory("user_temp", "Temporários", "", folders=(str(folder),), **kw)


def test_deletes_files_and_empty_subfolders_but_keeps_root(tmp_path, now):
    temp = tmp_path / "Temp"
    write(temp / "a.tmp", 100)
    write(temp / "sub" / "deep" / "b.log", 50)
    svc = service([temp_category(temp)], now)

    scan = svc.scan(["user_temp"])["user_temp"]
    assert (scan.files, scan.bytes) == (2, 150)

    (result,) = svc.clean(["user_temp"])
    assert result.files_deleted == 2 and result.bytes_freed == 150
    assert result.dirs_removed == 2
    assert temp.is_dir() and list(temp.iterdir()) == []


def test_skips_recent_files_by_default(tmp_path, now):
    temp = tmp_path / "Temp"
    write(temp / "velho.tmp", 10)
    recent = write(temp / "instalador_rodando" / "setup.msi", 10)
    os.utime(recent, (now, now))  # modificado "agora"

    svc = service([temp_category(temp)], now)
    scan = svc.scan(["user_temp"])["user_temp"]
    assert scan.files == 1 and scan.skipped_recent == 1

    (result,) = svc.clean(["user_temp"])
    assert result.files_deleted == 1 and result.skipped_recent == 1
    assert recent.exists()

    (result,) = svc.clean(["user_temp"], skip_recent=False)
    assert result.files_deleted == 1 and not recent.exists()


def test_never_follows_directory_links_out_of_the_folder(tmp_path, now):
    """Uma junction/symlink no %TEMP% não pode levar a apagar arquivos de fora."""
    temp = tmp_path / "Temp"
    documentos = tmp_path / "Documentos"
    precioso = write(documentos / "tese.docx", 999)
    write(temp / "lixo.tmp", 1)
    temp.mkdir(exist_ok=True)
    symlink_or_skip(documentos, temp / "atalho_para_documentos", is_dir=True)
    symlink_or_skip(precioso, temp / "link_arquivo.docx")

    svc = service([temp_category(temp)], now)
    assert svc.scan(["user_temp"])["user_temp"].files == 1
    (result,) = svc.clean(["user_temp"], skip_recent=False)

    assert result.files_deleted == 1
    assert precioso.read_bytes() == b"x" * 999
    assert (temp / "atalho_para_documentos").is_symlink()


def test_pattern_category_only_touches_matching_files(tmp_path, now):
    explorer = tmp_path / "Explorer"
    write(explorer / "thumbcache_256.db", 30)
    write(explorer / "iconcache_32.db", 30)
    write(explorer / "NotifyIcon" / "thumbcache_x.db", 30)  # subpasta: não recursivo
    cat = CleanupCategory("thumbnails", "Miniaturas", "", folders=(str(explorer),),
                          patterns=("thumbcache_*.db",), recursive=False, use_age_filter=False)
    (result,) = service([cat], now).clean(["thumbnails"])
    assert result.files_deleted == 1
    assert not (explorer / "thumbcache_256.db").exists()
    assert (explorer / "iconcache_32.db").exists()
    assert (explorer / "NotifyIcon" / "thumbcache_x.db").exists()


def test_files_in_use_are_skipped_without_stopping(tmp_path, now, monkeypatch):
    temp = tmp_path / "Temp"
    for i in range(30):
        write(temp / f"f{i}.tmp", 1)
    real_remove = os.remove

    def flaky_remove(path):
        name = os.path.basename(path)
        if name in ("f3.tmp", "f7.tmp"):
            raise PermissionError(13, "em uso")
        if name == "f9.tmp":
            raise OSError(32, "sharing violation")
        real_remove(path)

    monkeypatch.setattr(os, "remove", flaky_remove)
    (result,) = service([temp_category(temp)], now).clean(["user_temp"])
    assert result.files_deleted == 27
    assert result.skipped_in_use == 3
    assert len(result.errors) == 3


def test_excluded_dirs_are_untouched(tmp_path, now):
    temp = tmp_path / "Temp"
    own = write(temp / "_MEI12345" / "base_library.zip", 5)
    write(temp / "outro.tmp", 5)
    svc = service([temp_category(temp)], now, excluded_dirs={str(temp / "_MEI12345")})
    (result,) = svc.clean(["user_temp"], skip_recent=False)
    assert result.files_deleted == 1 and own.exists()


def test_cancel_stops_early(tmp_path, now):
    temp = tmp_path / "Temp"
    for i in range(10):
        write(temp / f"d{i}" / "x.tmp", 1)
    cancel = threading.Event()
    cancel.set()
    assert service([temp_category(temp)], now).clean(["user_temp"], cancel=cancel) == []


def test_only_selected_categories_run(tmp_path, now):
    a, b = tmp_path / "A", tmp_path / "B"
    write(a / "x", 1)
    write(b / "y", 1)
    cats = [temp_category(a), CleanupCategory("other", "B", "", folders=(str(b),))]
    service(cats, now).clean(["other"])
    assert (a / "x").exists() and not (b / "y").exists()


def test_recycle_bin_category(now):
    rb = FakeRecycleBin(size=5000, items=3)
    cat = CleanupCategory("recycle_bin", "Lixeira", "", is_recycle_bin=True, use_age_filter=False)
    svc = service([cat], now, recycle_bin=rb)
    scan = svc.scan(["recycle_bin"])["recycle_bin"]
    assert (scan.bytes, scan.files) == (5000, 3)
    (result,) = svc.clean(["recycle_bin"])
    assert rb.emptied and result.bytes_freed == 5000 and result.files_deleted == 3


def test_default_categories_dedupe_and_skip_missing(tmp_path):
    local = tmp_path / "Local"
    (local / "Temp").mkdir(parents=True)
    (local / "Microsoft" / "Windows" / "Explorer").mkdir(parents=True)
    windir = tmp_path / "Windows"
    (windir / "Prefetch").mkdir(parents=True)
    symlink_or_skip(local / "Temp", tmp_path / "TEMP~1", is_dir=True)  # "nome curto"
    env = {
        "LOCALAPPDATA": str(local),
        "TEMP": str(tmp_path / "TEMP~1"),
        "TMP": str(local / "Temp"),
        "SystemRoot": str(windir),
    }
    cats = {c.key: c for c in build_default_categories(env, include_recycle_bin=False)}

    assert cats["user_temp"].folders == (str(tmp_path / "TEMP~1"),)  # 3 caminhos, 1 pasta real
    assert "windows_temp" not in cats  # pasta não existe
    assert "recycle_bin" not in cats
    assert cats["prefetch"].default_selected is False and cats["prefetch"].warning
    assert cats["thumbnails"].patterns == ("thumbcache_*.db",)
