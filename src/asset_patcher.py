"""Experimental DX12 ComputeShader aliases built solely from a user's own asset.

This is a structural transformation, not shader compilation or a DX12 correctness
guarantee. Existing DX12 variants are always preserved without modification.
"""
from __future__ import annotations

import copy
import hashlib
import os
from pathlib import Path
import re
from typing import Callable

import UnityPy
from UnityPy.files import SerializedFile


class PatchError(Exception):
    """The input or generated output cannot be patched safely."""


Progress = Callable[[str], None]
DX11 = 2
DX12 = 18


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def _notify(progress: Progress | None, message: str) -> None:
    if progress is not None:
        progress(message)


def _load(data: bytes, description: str):
    try:
        env = UnityPy.load(data)
        files = list(env.files.values())
        if len(files) != 1 or not isinstance(files[0], SerializedFile):
            raise PatchError(f'{description}: expected one standalone serialized asset; bundles and containers are unsupported.')
        asset = files[0]
        if not re.fullmatch(r'2022\.3\.\d+[abfp]\d+', asset.unity_version):
            raise PatchError(f'{description}: Unity {asset.unity_version!r} is unsupported; this experiment supports only Unity 2022.3 assets.')
        if asset.header.version != 22:
            raise PatchError(f'{description}: unsupported serialized asset version {asset.header.version}.')
        if asset.header.file_size != len(data):
            raise PatchError(f'{description}: serialized asset length does not match the file header.')
        # Windows x64 is the tested CS2 target. A renderer tag alone cannot make
        # an asset compiled for another platform suitable for this patch.
        if int(asset.target_platform) != 19:
            raise PatchError(f'{description}: expected a Windows 64-bit asset, found target platform {asset.target_platform}.')
        objects = dict(asset.objects)
        if not objects:
            raise PatchError(f'{description}: asset contains no objects.')
        spans = []
        for path_id, obj in objects.items():
            if path_id != obj.path_id:
                raise PatchError(f'{description}: inconsistent object identity.')
            start, size = obj.byte_start, obj.byte_size
            if start < asset.header.data_offset or size < 0 or start + size > len(data):
                raise PatchError(f'{description}: object {path_id} lies outside the asset.')
            spans.append((start, start + size, path_id))
        spans.sort()
        for prior, current in zip(spans, spans[1:]):
            if current[0] < prior[1]:
                raise PatchError(f'{description}: overlapping object data.')
        return env, asset, objects
    except PatchError:
        raise
    except Exception as exc:
        raise PatchError(f'{description}: unable to parse a supported standalone Unity asset: {exc}') from exc


def _analyze_tree(tree, path_id):
    if not isinstance(tree, dict) or not isinstance(tree.get('m_Name'), str):
        raise PatchError(f'ComputeShader {path_id}: missing or malformed name.')
    variants = tree.get('variants')
    if not isinstance(variants, list) or not variants:
        raise PatchError(f'ComputeShader {path_id}: missing or empty variant list.')
    dx11, dx12 = [], []
    for index, variant in enumerate(variants):
        if not isinstance(variant, dict) or type(variant.get('targetRenderer')) is not int:
            raise PatchError(f'ComputeShader {path_id}, variant {index}: malformed renderer tag.')
        if type(variant.get('targetLevel')) is not int or not isinstance(variant.get('kernels'), list) or not isinstance(variant.get('constantBuffers'), list) or type(variant.get('resourcesResolved')) is not bool:
            raise PatchError(f'ComputeShader {path_id}, variant {index}: unexpected Unity 2022.3 variant structure.')
        if not variant['kernels'] or not all(isinstance(kernel, dict) for kernel in variant['kernels']):
            raise PatchError(f'ComputeShader {path_id}, variant {index}: missing or malformed kernels.')
        if variant['targetRenderer'] == DX11:
            dx11.append(variant)
        elif variant['targetRenderer'] == DX12:
            dx12.append(variant)
    if not dx11 and not dx12:
        raise PatchError(f'ComputeShader {path_id} ({tree["m_Name"]}): contains neither DX11 nor DX12 variants; cannot infer DX12 support.')
    return dx11, dx12


def _inspect_loaded(asset, objects):
    trees = {}
    dx11_count = dx12_count = existing = needs = 0
    coverage = []
    for path_id, obj in objects.items():
        if obj.type.name != 'ComputeShader':
            continue
        try:
            tree = obj.read_typetree()
        except Exception as exc:
            raise PatchError(f'ComputeShader {path_id}: cannot read complete type tree: {exc}') from exc
        dx11, dx12 = _analyze_tree(tree, path_id)
        trees[path_id] = tree
        dx11_count += len(dx11)
        dx12_count += len(dx12)
        if dx12:
            existing += 1
        else:
            needs += 1
        coverage.append({'pathId': path_id, 'name': tree['m_Name'], 'dx11Variants': len(dx11), 'dx12Variants': len(dx12), 'needsAlias': not bool(dx12)})
    if not trees:
        raise PatchError('Asset contains no ComputeShader objects; no supported patch can be inferred.')
    info = {
        'unityVersion': asset.unity_version,
        'unityPyVersion': UnityPy.__version__,
        'serializedVersion': asset.header.version,
        'targetPlatform': int(asset.target_platform),
        'objectCount': len(objects),
        'computeShaderCount': len(trees),
        'existingDx12Count': existing,
        'needsAliasCount': needs,
        'dx11VariantCount': dx11_count,
        'dx12VariantCount': dx12_count,
        'shaderCoverage': coverage,
        'status': 'patchable' if needs else 'already_supported',
    }
    return info, trees


def _read_source(path: Path) -> bytes:
    if not path.is_file():
        raise PatchError(f'Asset file does not exist: {path}')
    try:
        return path.read_bytes()
    except OSError as exc:
        raise PatchError(f'Cannot read asset {path}: {exc}') from exc


def inspect_asset(path) -> dict:
    """Inspect standalone Windows Unity2022.3 asset without writing anything."""
    source = Path(path).resolve()
    data = _read_source(source)
    _env, asset, objects = _load(data, source.name)
    info, _trees = _inspect_loaded(asset, objects)
    return dict(info, source=str(source), sourceBytes=len(data), sourceSha256=_sha(data))


def _expected_tree(tree):
    original = copy.deepcopy(tree)
    variants = original['variants']
    aliases = []
    for variant in variants:
        if variant['targetRenderer'] == DX11:
            alias = copy.deepcopy(variant)
            alias['targetRenderer'] = DX12
            aliases.append(alias)
    variants.extend(aliases)
    return original


def _metadata(asset):
    return {
        'unityVersion': asset.unity_version,
        'serializedVersion': asset.header.version,
        'platform': int(asset.target_platform),
        'typeTreeEnabled': asset._enable_type_tree,
        'userInformation': asset.userInformation,
        'externals': [(x.path, x.temp_empty, x.guid, x.type) for x in asset.externals],
        'scriptTypes': [(x.local_serialized_file_index, x.local_identifier_in_file) for x in asset.script_types],
    }


def _verify_output(original_data, output_data, source_asset, source_objects, original_trees, changed_ids):
    _out_env, output_asset, output_objects = _load(output_data, 'Generated output')
    if _metadata(source_asset) != _metadata(output_asset):
        raise PatchError('Verification failed: serialized asset metadata changed unexpectedly.')
    if source_objects.keys() != output_objects.keys():
        raise PatchError('Verification failed: object IDs changed.')
    for path_id, old in source_objects.items():
        new = output_objects[path_id]
        if old.type != new.type:
            raise PatchError(f'Verification failed: object {path_id} changed type.')
        if path_id not in changed_ids:
            old_raw = original_data[old.byte_start:old.byte_start + old.byte_size]
            new_raw = output_data[new.byte_start:new.byte_start + new.byte_size]
            if old_raw != new_raw:
                raise PatchError(f'Verification failed: unmodified object {path_id} changed bytes.')
        else:
            before = original_trees[path_id]
            expected = _expected_tree(before)
            try:
                actual = new.read_typetree()
            except Exception as exc:
                raise PatchError(f'Verification failed: cannot re-read changed object {path_id}: {exc}') from exc
            if actual != expected:
                raise PatchError(f'Verification failed: ComputeShader {path_id} differs from exact appended DX12 aliases.')
            if actual['variants'][:len(before['variants'])] != before['variants']:
                raise PatchError(f'Verification failed: original variant prefix changed in object {path_id}.')
    output_info, _trees = _inspect_loaded(output_asset, output_objects)
    if output_info['needsAliasCount']:
        raise PatchError('Verification failed: output still has compute shaders without DX12 coverage.')
    return output_info


def patch_asset(source, target, progress: Progress | None = None) -> dict:
    """Write a new verified staged asset; never replace source or an existing target.

    Already-supported inputs return outputWritten=False and leave target absent.
    progress, if supplied, receives human-readable strings. A successful result
    verifies structure and exact edits, not runtime graphics compatibility.
    """
    source = Path(source).resolve()
    target = Path(target).resolve()
    if source == target:
        raise PatchError('Source and output must be different files; patching in place is forbidden.')
    if target.exists():
        raise PatchError(f'Output already exists; refusing to overwrite it: {target}')
    _notify(progress, f'Inspecting {source.name}')
    original = _read_source(source)
    before_hash = _sha(original)
    _env, asset, objects = _load(original, source.name)
    info, trees = _inspect_loaded(asset, objects)
    result = dict(info, source=str(source), target=str(target), originalBytes=len(original), beforeSha256=before_hash)
    if not info['needsAliasCount']:
        _notify(progress, f'{source.name}: every compute shader already has a DX12 variant; leaving it unchanged')
        return dict(result, changedShaderCount=0, addedVariantCount=0, patchedBytes=len(original), afterSha256=before_hash, outputWritten=False, outputDx12CoveredShaderCount=info['computeShaderCount'])
    changed = set()
    added = 0
    _notify(progress, f'Preparing aliases for {info["needsAliasCount"]} compute shaders in {source.name}')
    try:
        for path_id, tree in trees.items():
            dx11, dx12 = _analyze_tree(tree, path_id)
            if dx12:
                continue
            objects[path_id].save_typetree(_expected_tree(tree))
            changed.add(path_id)
            added += len(dx11)
        output = asset.save()
    except PatchError:
        raise
    except Exception as exc:
        raise PatchError(f'Unable to serialize candidate asset: {exc}') from exc
    _notify(progress, f'Verifying every object and all shader variants in {source.name}')
    output_info = _verify_output(original, output, asset, objects, trees, changed)
    after_hash = _sha(output)
    if _sha(_read_source(source)) != before_hash:
        raise PatchError('Source asset changed while preparing the patch; no output written.')
    created = False
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            created = True
            stream.write(output)
            stream.flush()
            os.fsync(stream.fileno())
        if _sha(target.read_bytes()) != after_hash:
            raise PatchError('Written output failed its checksum verification.')
    except Exception as exc:
        if created:
            target.unlink(missing_ok=True)
        if isinstance(exc, PatchError):
            raise
        raise PatchError(f'Cannot write verified output: {exc}') from exc
    _notify(progress, f'{source.name}: verified staged output ready')
    return dict(result, changedShaderCount=len(changed), addedVariantCount=added, patchedBytes=len(output), afterSha256=after_hash, outputWritten=True, outputDx12CoveredShaderCount=output_info['existingDx12Count'])
