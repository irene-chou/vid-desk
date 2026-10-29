from vid_desk.core import sanitize_filename

def test_strips_unsafe_chars():
    assert sanitize_filename('a/b:c?d') == 'a_b_c_d'

def test_strips_trailing_dots_and_spaces():
    assert sanitize_filename(' name. ') == 'name'

def test_empty_after_sanitize_falls_back_to_video():
    assert sanitize_filename('???') == 'video'
    assert sanitize_filename('') == 'video'
