from bara.kicad_generated import kicad_source_url


def test_footprint_and_symbol_ids_point_into_the_official_library() -> None:
    fp = kicad_source_url("kicad:fp:Button_Switch_SMD:SW_SPST_PTS645", "Button_Switch_SMD")
    assert fp and fp.endswith("/Button_Switch_SMD.pretty/SW_SPST_PTS645.kicad_mod")
    sym = kicad_source_url("kicad:sym:Device:R", "Device")
    assert sym and sym.endswith("/Device.kicad_sym")


def test_other_ids_have_no_kicad_url() -> None:
    assert kicad_source_url("lcsc:C123", "x") is None
    assert kicad_source_url("kicad:fp:A:B", "") is None
