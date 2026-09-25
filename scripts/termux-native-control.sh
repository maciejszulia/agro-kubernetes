#!/data/data/com.termux/files/usr/bin/bash
set -eu
umask 077
exec python3 - "$@" <<'PY'
import argparse, hashlib, ipaddress, json, os, shlex, shutil, stat, subprocess, sys, tempfile, time
from pathlib import Path

K3S_SHA256 = 'c920706346d5ad4e5cd3c7bf1bb09ce71ebe07fec829e513e40f1caf98aed8bb'


def install_new(path, content, mode=0o600):
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_text() != content:
            raise ValueError('Existing file changed during setup: ' + str(path))
        return
    descriptor, temporary = tempfile.mkstemp(prefix='.native-control-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            stream.write(content)
            os.fchmod(stream.fileno(), mode)
        os.link(temporary, path)
    finally:
        os.unlink(temporary)


def wait_supervisor(service):
    deadline = time.monotonic() + 15
    fifos = [service / 'supervise/ok', service / 'log/supervise/ok']
    while not all(path.exists() and stat.S_ISFIFO(path.stat().st_mode) for path in fifos):
        if time.monotonic() >= deadline:
            raise RuntimeError('No runit supervisor FIFO within 15 seconds; service files are preserved')
        time.sleep(0.2)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Supervise the native Termux K3s control plane.')
    parser.add_argument('--node-ip', required=True)
    args = parser.parse_args(argv)
    try:
        address = ipaddress.IPv4Address(args.node_ip)
    except ipaddress.AddressValueError:
        raise ValueError('Node IP must be a valid IPv4 address') from None
    if address.is_loopback or address.is_multicast or address.is_unspecified:
        raise ValueError('Node IP must not be loopback, multicast or unspecified')
    if not os.environ.get('PREFIX'):
        raise ValueError('Run this helper inside the existing Termux environment')
    prefix = Path(os.environ['PREFIX']).resolve(strict=True)
    state = Path.home() / 'mobile-lab/native-control'
    service_root = prefix / 'var/service'
    service = service_root / 'agro-k3s-control'
    binary = state / 'bin/k3s'
    config = state / 'config.yaml'
    bundled = state / 'data/data/current/bin'
    if any(character.isspace() for character in str(prefix)):
        raise ValueError('Unsupported whitespace in Termux prefix')
    if state.is_symlink() or service.is_symlink() or not service_root.is_dir():
        raise ValueError('Expected private state and an existing Termux service directory')
    if not state.is_dir() or state.stat().st_mode & 0o077:
        raise ValueError('State directory must already exist with private permissions')
    for name in ('sh', 'proot', 'sv', 'svlogd', 'termux-wake-lock'):
        if not os.access(prefix / 'bin' / name, os.X_OK):
            raise ValueError('Missing Termux prerequisite: ' + name)
    if not (prefix / 'etc/resolv.conf').is_file():
        raise ValueError('Missing Termux resolver configuration')
    if not os.access(binary, os.X_OK):
        raise ValueError('Stage the executable official launcher at bin/k3s first')
    with binary.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != K3S_SHA256:
            raise ValueError('Staged K3s launcher checksum mismatch')

    settings = {
        'node-name': 'xa2-01-control', 'rootless': True, 'disable-agent': True,
        'egress-selector-mode': 'cluster', 'bind-address': '127.0.0.1',
        'https-listen-port': 16443, 'advertise-address': '10.0.2.2',
        'tls-san': ['127.0.0.1', '10.0.2.2'], 'node-ip': str(address),
        'data-dir': str(state / 'data'), 'write-kubeconfig': str(state / 'kubeconfig'),
        'write-kubeconfig-mode': '0600', 'resolv-conf': str(prefix / 'etc/resolv.conf'),
        'disable': ['traefik', 'servicelb', 'metrics-server', 'local-storage'],
        'disable-helm-controller': True,
    }
    quote = shlex.quote
    run = (f'#!{prefix}/bin/sh\nexec 2>&1\numask 077\n'
           f'export K3S_DATA_DIR={quote(str(state / "data"))}\n'
           f'export TMPDIR={quote(str(state / "tmp"))}\nexport GOMAXPROCS=2\n'
           f'export PATH={quote(str(bundled))}:"$PATH"\ncd {quote(str(state))}\n'
           f'exec {quote(str(prefix / "bin/proot"))} -r / -w {quote(str(state))} '
           f'{quote(str(bundled / "k3s-server"))} server --config {quote(str(config))}\n')
    log_run = (f'#!{prefix}/bin/sh\numask 077\n'
               f'exec {quote(str(prefix / "bin/svlogd"))} -tt {quote(str(state / "log"))}\n')
    files = {config: json.dumps(settings, indent=2) + '\n',
             state / 'log/config': 's1048576\nn3\n',
             service / 'run': run, service / 'log/run': log_run}
    for path, content in files.items():
        if path.is_symlink() or (path.exists() and (not path.is_file() or path.read_text() != content)):
            raise ValueError('Refusing incompatible existing file: ' + str(path))
    for path in (state / 'data', state / 'tmp', state / 'log', service / 'log'):
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            raise ValueError('Refusing incompatible runtime directory: ' + str(path))
    if not config.exists() and any(path.name != 'bin' for path in state.iterdir()):
        raise ValueError('Existing state has no matching configuration; refusing to adopt it')
    if service.exists():
        if not config.exists() or not all(path.is_file() and os.access(path, os.X_OK)
                                         for path in (service / 'run', service / 'log/run')):
            raise ValueError('Refusing to adopt an incomplete existing service')
        if any(path.name not in {'run', 'log', 'supervise'} for path in service.iterdir()):
            raise ValueError('Existing service has unsupported supervision files')
        if any(path.name not in {'run', 'supervise'} for path in (service / 'log').iterdir()):
            raise ValueError('Existing log service has unsupported supervision files')

    # All identity checks precede installation, extraction, wake locks and supervision changes.
    for name in ('data', 'tmp', 'log'):
        (state / name).mkdir(mode=0o700, exist_ok=True)
    install_new(config, files[config])
    install_new(state / 'log/config', files[state / 'log/config'])
    environment = dict(os.environ, K3S_DATA_DIR=str(state / 'data'), TMPDIR=str(state / 'tmp'), GOMAXPROCS='2')
    subprocess.run([str(prefix / 'bin/proot'), '-r', '/', '-w', str(state), str(binary),
                    'kubectl', 'version', '--client', '-o', 'json'],
                   env=environment, check=True, capture_output=True, timeout=120)
    if not os.access(bundled / 'k3s-server', os.X_OK):
        raise ValueError('Verified launcher did not provide an executable k3s-server payload')
    if not service.exists():
        staging = Path(tempfile.mkdtemp(prefix='.agro-k3s-control-', dir=service_root))
        try:
            (staging / 'log').mkdir(mode=0o700)
            install_new(staging / 'run', run, 0o700)
            install_new(staging / 'log/run', log_run, 0o700)
            if service.exists():
                raise ValueError('Service appeared during setup; refusing to replace it')
            staging.rename(service)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
    subprocess.run([str(prefix / 'bin/termux-wake-lock')], check=True, capture_output=True, timeout=10)
    wait_supervisor(service)
    subprocess.run([str(prefix / 'bin/sv'), '-w', '10', 'up', str(service)],
                   check=True, capture_output=True, timeout=15)
    print('Native control service supervised:', service)
    print('API readiness and Kubernetes node/workload readiness require separate checks.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print('Native control setup failed:', error, file=sys.stderr)
        sys.exit(1)
PY
