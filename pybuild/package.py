import importlib
import os.path
import pathlib
from typing import Iterator, List

from . import env
from .arch import arm, x86, mips, arm64
from .patch import Patch, RemotePatch
from .source import Source, URLSource
from .util import BASE, target_arch


class Package:
    BUILDDIR = BASE / 'build'

    source: Source = None
    extra_sources: List[Source] = []
    patches: List[Patch] = []

    def __init__(self):
        self.name = type(self).__name__.lower()

        self.init_build_env()

        for patch in self.patches:
            patch.package = self

    @property
    def sources(self) -> List[Source]:
        return [self.source] + self.extra_sources + [
            URLSource(patch.url)
            for patch in self.patches if isinstance(patch, RemotePatch)]

    def init_build_env(self):
        self.env = {}

        self.DESTDIR = self.BUILDDIR / 'target'

        ANDROID_NDK = self._check_ndk()

        HOST_OS = os.uname().sysname.lower()

        if HOST_OS not in ('linux', 'darwin'):
            raise Exception(f'Unsupported system {HOST_OS}')

        self.ANDROID_PLATFORM = target_arch().__class__.__name__

        self.TOOL_PREFIX = (ANDROID_NDK / 'toolchains' /
                            target_arch().ANDROID_TOOLCHAIN /
                            'prebuilt' / f'{HOST_OS}-x86_64')
        CLANG_PREFIX = (ANDROID_NDK / 'toolchains' /
                        'llvm' / 'prebuilt' / f'{HOST_OS}-x86_64')

        LLVM_BASE_FLAGS = [
            '-target', target_arch().LLVM_TARGET,
            '-gcc-toolchain', self.TOOL_PREFIX,
        ]

        ARCH_SYSROOT = (ANDROID_NDK / 'platforms' /
                        f'android-{env.android_api_level}' /
                        f'arch-{self.ANDROID_PLATFORM}' / 'usr')
        UNIFIED_SYSROOT = ANDROID_NDK / 'sysroot' / 'usr'

        cflags = ['-fPIC']
        if isinstance(target_arch(),  (arm, x86, mips, arm64)):
            cflags += ['-fno-integrated-as']

        self.env.update({
            'ANDROID_API_LEVEL': env.android_api_level,

            # Sysroots
            'ARCH_SYSROOT': ARCH_SYSROOT,
            'UNIFIED_SYSROOT': UNIFIED_SYSROOT,

            # Compilers
            'CC': f'{CLANG_PREFIX}/bin/clang',
            'CXX': f'{CLANG_PREFIX}/bin/clang++',
            'CPP': f'{CLANG_PREFIX}/bin/clang -E',

            # Compiler flags
            'CPPFLAGS': LLVM_BASE_FLAGS + [
                '--sysroot=' + str(UNIFIED_SYSROOT),
                f'-I{UNIFIED_SYSROOT}/include/{target_arch().ANDROID_TARGET}',
                f'-D__ANDROID_API__={env.android_api_level}',
                f'-I{self.DESTDIR}/usr/include',
            ],
            'CFLAGS': cflags,
            'CXXFLAGS': cflags,
            'LDFLAGS': LLVM_BASE_FLAGS + [
                '--sysroot=' + str(ARCH_SYSROOT),
                '-pie',
                f'-L{self.DESTDIR}/usr/lib'
            ],

            # pkg-config
            'PKG_CONFIG_LIBDIR': f'{self.DESTDIR}/usr/lib/pkgconfig',
            'PKG_CONFIG_SYSROOT_DIR': self.DESTDIR,
        })

        # XXX -O2 is a workaround for linker failures on MIPS
        # See https://github.com/android-ndk/ndk/issues/261
        if self.ANDROID_PLATFORM == 'mips':
            self.env['CFLAGS'].append('-O2')

        for prog in ('ar', 'as', 'ld', 'objcopy', 'objdump', 'ranlib', 'strip', 'readelf'):
            self.env[prog.upper()] = self.TOOL_PREFIX / 'bin' / f'{target_arch().ANDROID_TARGET}-{prog}'

    @property
    def filesdir(self) -> pathlib.Path:
        return BASE / 'mk' / self.name

    def fresh(self) -> bool:
        return not (self.source.source_dir / 'Makefile').exists()

    def run(self, cmd: List[str]) -> None:
        self.source.run_in_source_dir(cmd)

    def run_with_env(self, cmd: List[str]) -> None:
        self.source.run_in_source_dir(cmd, env=self.env)

    def _check_ndk(self) -> pathlib.Path:
        ndk_path = os.getenv('ANDROID_NDK')
        if not ndk_path:
            raise Exception('Requires environment variable $ANDROID_NDK')
        ndk = pathlib.Path(ndk_path)

        if not (ndk / 'sysroot').exists():
            raise Exception('Requires Android NDK r14 beta1 or above')

        return ndk

    def prepare(self):
        raise NotImplementedError

    def build(self):
        raise NotImplementedError


def import_package(pkgname: str) -> Package:
    pkgmod = importlib.import_module(f'pybuild.packages.{pkgname}')
    for symbol_name in dir(pkgmod):
        symbol = getattr(pkgmod, symbol_name)
        if type(symbol) == type and symbol_name.lower() == pkgname:
            return symbol()

    # XXX: mypy asks for an explicit `return`. Is it necessary?
    return None


def enumerate_packages() -> Iterator[Package]:
    for child in (pathlib.Path(__file__).parent / 'packages').iterdir():
        pkgname, ext = os.path.splitext(os.path.basename(child))
        if ext != '.py':
            continue
        yield import_package(pkgname)
