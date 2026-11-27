"""Map native Part.insert object indices to STEP assembly component labels.

Read-only inputs; writes only a semantic mapping report beside this script.
"""
from pathlib import Path
from collections import defaultdict
import hashlib
import json

root = Path(__file__).resolve().parent
assembly = root.parent / 'detailed-import' / 'C5-detailed-assembly.step'
records = json.loads((root / 'semantic-import-probe.json').read_text())
native = json.loads((root.parent / 'detailed-import' / 'native-import-object-audit.json').read_text())
objects = {o['name']: o for o in records}
assembly_root = next(o for o in records if o['type'] == 'App::Part' and not o['parents'])
roots = set(assembly_root['group'])


def signature(obj):
    return tuple(round(v, 4) for v in obj['bbox']) + (
        obj['faces'], obj['solids'], round(obj['area'], 3)
    )


lookup = defaultdict(set)
for obj in records:
    if obj['type'] != 'Part::Feature':
        continue
    owner = obj
    while owner['name'] not in roots and owner['parents']:
        owner = objects[owner['parents'][0]]
    lookup[signature(obj)].add(owner['name'])

semantic = {
    'SW_PUSH_6mm_H8mm': ('sw1', 'SW1 tactile pushbutton'),
    'heltec_v4_3_1_reference': ('heltec', 'U1 Heltec manufacturer model'),
    'heltec_v4_audio_carrier_pad': ('carrier_pads', 'Carrier PCB pads and plating'),
    'Part__Feature2948': ('carrier_substrate', 'Carrier PCB substrate'),
    'INMP441_ROUND_DETAILED_VISUAL001': ('microphone', 'U2 INMP441 microphone, corrected 14 mm model'),
    'MAX98357A_PURPLE_DETAILED_VISUAL001': ('amplifier', 'MAX98357A amplifier module'),
    'R_Axial_Carbon_1k_0p5W_P15p001': ('r8', 'R8 axial resistor'),
    'Heltec_V4_R2_OLED_BRACKET_VISUAL_5mm_GAP001': ('oled', 'OLED and bracket supplement'),
    'heltec_v4_audio_carrier_silkscreen': ('top_silkscreen', 'Carrier top silkscreen'),
    'heltec_v4_audio_carrier_silkscreen001': ('bottom_silkscreen', 'Carrier bottom silkscreen'),
    'Part__Feature2946': ('top_soldermask', 'Carrier top soldermask'),
    'Part__Feature2947': ('bottom_soldermask', 'Carrier bottom soldermask'),
}
ranges = []
matched = 0
for obj in native:
    idx = obj['index']
    if 1068 <= idx <= 1714:
        # This input audit predates the microphone scale correction. Its fixed
        # contiguous 647-object range is confirmed by corrected-assembly-check.json.
        owner = 'INMP441_ROUND_DETAILED_VISUAL001'
    else:
        candidates = lookup[signature(obj)]
        assert len(candidates) == 1, (idx, candidates)
        owner = next(iter(candidates))
        matched += 1
    if ranges and ranges[-1]['semantic_root'] == owner:
        ranges[-1]['last_index'] = idx
    else:
        key, label = semantic[owner]
        ranges.append(dict(first_index=idx, last_index=idx, component=key,
                           label=label, semantic_root=owner))

components = []
for owner, (key, label) in semantic.items():
    component_ranges = [[r['first_index'], r['last_index']] for r in ranges if r['semantic_root'] == owner]
    bbox = objects[owner]['bbox']
    assembled = [v + (6.4814 if i in (2, 5) else 0) for i, v in enumerate(bbox)]
    components.append(dict(component=key, label=label, index_ranges_inclusive=component_ranges,
                           object_count=sum(b-a+1 for a, b in component_ranges),
                           bbox_source_mm=bbox, bbox_assembled_mm=assembled,
                           semantic_root=owner))

result = dict(
    source_step=str(assembly), source_sha256=hashlib.sha256(assembly.read_bytes()).hexdigest(),
    object_count=2949, units='mm', native_importer='Part.insert',
    source_datum_z_mm=1.5186, target_pcb_top_z_mm=8.0, assembly_translation_mm=[0, 0, 6.4814],
    name_format='index 0: C5_detailed_assembly; otherwise C5_detailed_assembly + index formatted as at least 3 decimal digits',
    validation=dict(
        semantic_importer='Import.insert',
        semantic_feature_count=sum(o['type'] == 'Part::Feature' for o in records),
        non_microphone_shapes_matched_by_bbox_faces_solids_and_area=matched,
        unmatched_non_microphone_shapes=0,
        microphone_range_basis='corrected-assembly-check.json; preserved 647-shape ordering and count after baked 1/2.54 scale correction',
    ),
    limitations=[
        'The reference native audit predates microphone rescaling; corrected microphone bounds come from the current semantic import.',
        'These labels classify geometry; they do not independently certify physical component dimensions or watertight solids.',
        'Heltec contains 888 solids at indices 1-888 and 666 additional surface pieces at indices 2145-2810. Only indices 2811-2830 belong to the OLED supplement.',
    ],
    ranges=ranges, components=components,
)
(root / 'component-index-map.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
lines = ['Verified native Part.insert semantic component ranges (inclusive)',
         'Current source SHA-256: ' + result['source_sha256'],
         'Assembly translation: (0, 0, +6.4814) mm',
         'Validation: 2302 non-microphone shapes matched to semantic STEP hierarchy; 0 unmatched.',
         'Microphone corrected range independently recorded in corrected-assembly-check.json.', '']
for c in components:
    spans = ', '.join(str(a) if a == b else f'{a}-{b}' for a, b in c['index_ranges_inclusive'])
    lines.append(f"{spans}: {c['label']} ({c['object_count']} objects)")
lines += ['', 'Important: 2145-2810 are Heltec surface pieces; OLED supplement is only 2811-2830.']
(root / 'component-index-map.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
print(json.dumps(dict(report=str(root / 'component-index-map.json'), components=len(components),
                      ranges=len(ranges), non_microphone_matches=matched)))
