from .env import packages
from .package import import_package

dependency = {
    'readline': ['ncurses'],
}

built_packags: set = set()


def build_package(pkgname: str) -> None:
    if pkgname in built_packags:
        return

    for dep in dependency.get(pkgname, []):
        build_package(dep)

    pkg = import_package(pkgname)

    if pkg.fresh():
        for src in pkg.sources:
            src.download()

        for patch in getattr(pkg, 'patches', []):
            patch.apply(pkg.source)
        try:
            pkg.prepare()
        except NotImplementedError:
            print('Skipping prepare step')

    pkg.build()

    built_packags.add(pkgname)


def main():
    for pkgname in packages:
        build_package(pkgname)
    build_package('python')
