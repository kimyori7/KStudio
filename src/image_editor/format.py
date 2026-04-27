"""`.kstudio` (ZIP 컨테이너) 저장.

구조:
  manifest.json         — 포맷 메타 + 레이어 목록 (canvas_size, layers[])
  thumbnail.png         — 미리보기 (첫 ImageLayer 의 합성을 256으로 다운샘플)
  layers/{id}_image.png — ImageLayer 픽셀 (ARGB32 PNG)
  layers/{id}_mask.png  — ImageLayer 마스크 (선택)
  layers/{id}_annotation.json — AnnotationLayer 아이템들

Task 13 의 reader 가 이 구조를 그대로 읽어들임.
"""
from __future__ import annotations

import json
import zipfile
from itertools import count
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPoint, QSize, Qt
from PySide6.QtGui import QColor, QImage

if TYPE_CHECKING:
    from .layer_model import LayerStack

FORMAT_VERSION = 1


def _qimage_to_png_bytes(img: QImage) -> bytes:
    buf = QBuffer()
    buf.open(QIODevice.ReadWrite)
    img.save(buf, "PNG")
    return bytes(buf.data())


def _serialize_annotation_items(layer) -> dict:
    """AnnotationLayer 의 아이템들을 JSON 호환 dict 로 직렬화.

    좌표는 모두 scene 공간 (item.pos() + 로컬 geometry).
    Task 13 의 reader 가 같은 shape 로 deserialize 한다.
    """
    from .items.arrow import ArrowAnnotationItem
    from .items.rect import RectAnnotationItem
    from .items.text import TextAnnotationItem

    items: list[dict] = []
    for it in layer.items():
        if isinstance(it, ArrowAnnotationItem):
            # start()/end() 는 로컬 좌표 — pos() 를 더해 scene 좌표로
            p = it.pos()
            s = it.start()
            e = it.end()
            items.append({
                "type": "arrow",
                "from": [p.x() + s.x(), p.y() + s.y()],
                "to": [p.x() + e.x(), p.y() + e.y()],
                "color": it.color().name(),  # "#RRGGBB"
                "thickness": int(it.thickness_step()),
            })
        elif isinstance(it, RectAnnotationItem):
            # rect() 는 로컬 좌표 — pos() 를 더해 scene 좌표로
            p = it.pos()
            r = it.rect()
            items.append({
                "type": "rect",
                "rect": [
                    p.x() + r.x(),
                    p.y() + r.y(),
                    r.width(),
                    r.height(),
                ],
                "color": it.color().name(),
                "thickness": int(it.thickness_step()),
            })
        elif isinstance(it, TextAnnotationItem):
            p = it.pos()
            font = it.font()
            items.append({
                "type": "text",
                "pos": [p.x(), p.y()],
                "text": it.text(),
                "font_size": int(font.pointSize()),
                "color": it.color().name(),
            })
    return {"items": items}


def write_kstudio(stack: "LayerStack", path: Path) -> None:
    """LayerStack 을 `.kstudio` ZIP 파일로 저장."""
    from .layers.annotation_layer import AnnotationLayer
    from .layers.image_layer import ImageLayer

    manifest_layers: list[dict] = []
    blob_files: dict[str, bytes] = {}

    for l in stack.layers:
        common = {
            "id": l.id,
            "name": l.name,
            "visible": bool(l.visible),
            "opacity": float(l.opacity),
        }
        if isinstance(l, ImageLayer):
            img_path = f"layers/{l.id}_image.png"
            blob_files[img_path] = _qimage_to_png_bytes(l.pixmap)
            mask_path = None
            if l.mask is not None:
                mask_path = f"layers/{l.id}_mask.png"
                blob_files[mask_path] = _qimage_to_png_bytes(l.mask)
            manifest_layers.append({
                **common,
                "type": "image",
                "offset": [l.offset.x(), l.offset.y()],
                "image_path": img_path,
                "mask_path": mask_path,
            })
        elif isinstance(l, AnnotationLayer):
            data_path = f"layers/{l.id}_annotation.json"
            blob_files[data_path] = json.dumps(
                _serialize_annotation_items(l),
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8")
            manifest_layers.append({
                **common,
                "type": "annotation",
                "data_path": data_path,
            })

    manifest = {
        "format_version": FORMAT_VERSION,
        "canvas_size": [stack.canvas_size.width(), stack.canvas_size.height()],
        "active_layer_id": stack.active_layer_id,
        "layers": manifest_layers,
    }

    # 썸네일: 첫 ImageLayer 의 합성을 256으로 다운샘플. 없으면 투명 placeholder.
    thumb = QImage(stack.canvas_size, QImage.Format_ARGB32)
    thumb.fill(Qt.transparent)
    for l in stack.layers:
        if isinstance(l, ImageLayer):
            thumb = l.composed_pixmap().scaled(
                256, 256, Qt.KeepAspectRatio, Qt.SmoothTransformation,
            )
            break

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(
            "manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2),
        )
        z.writestr("thumbnail.png", _qimage_to_png_bytes(thumb))
        for fn, blob in blob_files.items():
            z.writestr(fn, blob)


# ---------------------------------------------------------------------------
# Reader (Task 13)
# ---------------------------------------------------------------------------


def _png_bytes_to_qimage(blob: bytes) -> QImage:
    """PNG 바이트 → QImage. 실패 시 null QImage 반환."""
    img = QImage()
    img.loadFromData(QByteArray(blob), "PNG")
    return img


def _deserialize_annotation_items(layer, data: dict) -> None:
    """JSON dict → AnnotationLayer items.

    좌표는 scene 공간 그대로 — pos()=(0,0) 인 상태로 아이템 로컬 geometry 에
    저장한다 (Task 12 writer 가 평탄화한 형식에 맞춤).
    """
    from PySide6.QtCore import QPointF, QRectF

    from .items.arrow import ArrowAnnotationItem
    from .items.rect import RectAnnotationItem
    from .items.text import TextAnnotationItem

    for it in data.get("items", []):
        kind = it.get("type")
        if kind == "arrow":
            start = QPointF(*it["from"])
            end = QPointF(*it["to"])
            color = QColor(it.get("color", "#FF0000"))
            thickness = int(it.get("thickness", 2))
            arr = ArrowAnnotationItem(start, end, color, thickness)
            layer.add_item(arr)
        elif kind == "rect":
            r = it["rect"]
            rect = QRectF(r[0], r[1], r[2], r[3])
            color = QColor(it.get("color", "#FFFF00"))
            thickness = int(it.get("thickness", 2))
            ri = RectAnnotationItem(rect, color, thickness)
            layer.add_item(ri)
        elif kind == "text":
            pos = QPointF(*it["pos"])
            text = it.get("text", "")
            color = QColor(it.get("color", "#000000"))
            ti = TextAnnotationItem(pos, text, color)
            # font_size 는 forward-compat 정보로만 저장됨 — TextAnnotationItem 은
            # 고정 폰트(FONT_POINT_SIZE=18)를 사용하므로 적용하지 않는다.
            layer.add_item(ti)


def read_kstudio(path: Path) -> "LayerStack":
    """`.kstudio` ZIP → LayerStack 복원.

    잘못된 ZIP 이거나 manifest.json 이 없으면 zipfile.BadZipFile 또는 KeyError 가
    발생한다 (호출 측에서 캐치).
    """
    from .layer_model import LayerStack
    from .layers.annotation_layer import AnnotationLayer
    from .layers.image_layer import ImageLayer

    path = Path(path)
    with zipfile.ZipFile(path, "r") as z:
        manifest = json.loads(z.read("manifest.json").decode("utf-8"))
        version = manifest.get("format_version", 1)
        if version > FORMAT_VERSION:
            raise ValueError(
                f"이 파일은 더 새 버전의 KStudio 포맷(v{version})입니다. "
                f"현재 지원: v{FORMAT_VERSION}."
            )
        canvas_size = QSize(*manifest["canvas_size"])
        stack = LayerStack(canvas_size)
        for ldata in manifest["layers"]:
            if ldata["type"] == "image":
                pix = _png_bytes_to_qimage(z.read(ldata["image_path"]))
                mask = None
                if ldata.get("mask_path"):
                    mask = _png_bytes_to_qimage(z.read(ldata["mask_path"]))
                offset_xy = ldata.get("offset", [0, 0])
                offset = QPoint(int(offset_xy[0]), int(offset_xy[1]))
                layer = ImageLayer(
                    id=ldata["id"],
                    name=ldata["name"],
                    pixmap=pix,
                    mask=mask,
                    offset=offset,
                    visible=ldata.get("visible", True),
                    opacity=ldata.get("opacity", 1.0),
                )
                stack.add_layer(layer)
            elif ldata["type"] == "annotation":
                layer = AnnotationLayer(
                    id=ldata["id"],
                    name=ldata["name"],
                    canvas_size=canvas_size,
                    visible=ldata.get("visible", True),
                    opacity=ldata.get("opacity", 1.0),
                )
                data = json.loads(z.read(ldata["data_path"]).decode("utf-8"))
                _deserialize_annotation_items(layer, data)
                stack.add_layer(layer)
        if manifest.get("active_layer_id") is not None:
            stack.set_active_layer(manifest["active_layer_id"])
    # _id_seq 동기화: 로드된 레이어 id 와 충돌 없도록 max+1 부터 재시작
    max_id = max((l.id for l in stack.layers), default=0)
    stack._id_seq = count(max_id + 1)
    return stack
