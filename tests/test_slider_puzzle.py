import base64
import io

from PIL import Image

from backend.features.verification.slider_puzzle import new_puzzle, render_puzzle


def test_puzzle_images_are_stable_pngs_and_do_not_disclose_seed_or_target():
    seed, target = new_puzzle()
    view = render_puzzle(seed, int(target))
    assert render_puzzle(seed, int(target)) == view
    assert set(view) == {"id", "background", "piece", "width", "height", "piece_size", "top"}
    assert seed not in str(view)
    for key, size in [("background", (320, 160)), ("piece", (48, 48))]:
        prefix, data = view[key].split(",")
        assert prefix == "data:image/png;base64"
        image = Image.open(io.BytesIO(base64.b64decode(data)))
        assert image.format == "PNG" and image.size == size
        assert not image.info
        if key == "piece":
            assert image.mode == "RGBA" and image.getextrema()[3] == (0, 255)
    other_seed, other_target = new_puzzle()
    assert render_puzzle(other_seed, int(other_target))["id"] != view["id"]
