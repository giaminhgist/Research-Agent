from research_agent import config, paths


def test_find_project_root_walks_up(project):
    nested = project / "a" / "b" / "c"
    nested.mkdir(parents=True)
    assert paths.find_project_root(nested) == project.resolve()


def test_find_project_root_none_outside(tmp_path, tmp_home):
    d = tmp_path / "plain"
    d.mkdir()
    assert paths.find_project_root(d) is None


def test_config_layering(project):
    toml = project / ".research-agent" / "project.toml"
    toml.write_text(toml.read_text() + "\n[budget]\nmax_usd_per_session = 2.5\n")
    cfg = config.load(project)
    assert config.get(cfg, "budget.max_usd_per_session") == 2.5
    assert config.get(cfg, "budget.max_usd_per_project") == 100.0
    assert config.get(cfg, "data.protected_paths") == ["data/raw"]
    assert config.get(cfg, "no.such.key", 7) == 7


def test_user_config_layer(project, tmp_home):
    (tmp_home["ra"] / "config.toml").write_text("[budget]\nmax_usd_per_project = 50.0\n")
    assert config.get(config.load(project), "budget.max_usd_per_project") == 50.0


def test_is_within(project):
    assert paths.is_within(project / "x", project)
    assert not paths.is_within(project.parent, project)


def test_homes_from_env(tmp_home):
    assert paths.ra_home() == tmp_home["ra"]
    assert paths.claude_home() == tmp_home["claude"]
