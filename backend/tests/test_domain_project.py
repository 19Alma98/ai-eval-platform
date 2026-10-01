from aiobs.domain.project import Project, slugify


def test_slugify_basic() -> None:
    assert slugify("My Demo App") == "my-demo-app"


def test_slugify_strips_punctuation() -> None:
    assert slugify("Hello, World!") == "hello-world"


def test_slugify_empty_falls_back() -> None:
    assert slugify("   ") == "project"


def test_project_create_generates_slug() -> None:
    project = Project.create(name="Support Bot")
    assert project.name == "Support Bot"
    assert project.slug == "support-bot"
    assert project.id is not None


def test_project_create_with_explicit_slug() -> None:
    project = Project.create(name="Support Bot", slug="custom-slug")
    assert project.slug == "custom-slug"


def test_project_create_rejects_empty_name() -> None:
    try:
        Project.create(name="   ")
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "empty" in str(exc).lower()
