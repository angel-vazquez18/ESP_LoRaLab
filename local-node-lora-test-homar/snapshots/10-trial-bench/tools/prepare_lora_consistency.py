"""Check the two OLED LoRa boards and leave them idle at test 0/10.

This preparation command never sends LOAD, ARM or TX. It cannot start a radio
transfer. Full per-port logs and a JSON readiness result are preserved.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from lora_transfer_bench import Connection, discover_nodes, validate_hello, utc_now


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ports', nargs=2, default=['COM6', 'COM7'])
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
    folder = args.output_dir or root / 'captures' / f'{stamp}-lora-consistency-ready'
    folder.mkdir(parents=True, exist_ok=False)
    result = {'started_at': utc_now(), 'purpose': 'readiness_only_no_radio_test',
              'test_started': False, 'passed': False, 'nodes': [],
              'allowed_commands': ['HELLO', 'STOP', 'TEST 0 10', 'ROLE TX', 'ROLE RX', 'STATUS']}
    connections = []
    try:
        for node in discover_nodes(args.ports):
            conn = Connection(node, folder)
            connections.append(conn)
            conn.open()
        for conn in connections:
            hello = conn.request('HELLO', 'hello')['message']
            validate_hello(conn.node, hello)
            if hello.get('firmware') != 'lora-integrity-2-oled':
                raise RuntimeError(f"{conn.node['port']}: OLED firmware has not been uploaded")
            if not hello.get('oled_ready') or not hello.get('oled_layout_ok'):
                raise RuntimeError(f"{conn.node['port']}: OLED readiness/layout check failed")
            if hello.get('tx_runs_started') != 0 or hello.get('rf_tx_calls_total') != 0:
                raise RuntimeError(f"{conn.node['port']}: RF counters are nonzero; not a fresh idle preparation")
            conn.hello = hello
        for conn in connections:
            role = 'TX' if conn.node['label'] == 'Heltec-A' else 'RX'
            conn.request('STOP', 'stopped')
            counter = conn.request('TEST 0 10', 'test')['message']
            if (counter.get('current'), counter.get('total')) != (0, 10):
                raise RuntimeError('Wrong test-counter acknowledgement')
            conn.request(f'ROLE {role}', 'role', predicate=lambda m, r=role: m.get('role') == r)
            status = conn.request('STATUS', 'status')['message']
            expected = {'role': role, 'state': 'IDLE', 'test_current': 0, 'test_total': 10,
                        'armed': False, 'transmitting': False, 'loaded': False,
                        'tx_runs_started': 0, 'rf_tx_calls_total': 0,
                        'oled_ready': True, 'oled_layout_ok': True}
            if any(status.get(key) != value for key, value in expected.items()):
                raise RuntimeError(f"{conn.node['port']}: unexpected readiness status {status}")
            result['nodes'].append({'identity': conn.node, 'hello': conn.hello, 'status': status})
            print(f"{conn.node['label']} / {conn.node['port']}: {role}, IDLE, Test 0 of 10; OLED ready; RF calls 0", flush=True)
        result['passed'] = True
    except Exception as exc:
        result['error'] = str(exc)
        print(f'Preparation failed: {exc}', file=sys.stderr)
    finally:
        for conn in connections:
            try:
                if conn.serial.is_open:
                    conn.request('STOP', 'stopped', timeout=3)
            except Exception as exc:
                result.setdefault('cleanup_errors', []).append(str(exc))
                result['passed'] = False
            try:
                conn.close()
            except Exception as exc:
                result.setdefault('cleanup_errors', []).append(str(exc))
                result['passed'] = False
        result['connections_closed'] = all(not c.serial.is_open for c in connections)
        result['finished_at'] = utc_now()
        (folder / 'summary.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
        print(f'Evidence: {folder}')
    return 0 if result['passed'] and result['connections_closed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
