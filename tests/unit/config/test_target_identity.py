"""target_identity: the one definition of "same destination" for a validated output target."""

from __future__ import annotations

from decoy_engine.config import FileTarget, GCSTarget, S3Target, target_identity


def test_file_paths_are_normalized() -> None:
    a = FileTarget(type="file", format="csv", path="out/a.csv")
    b = FileTarget(type="file", format="csv", path="out/./a.csv")
    assert target_identity(a) == target_identity(b) == ("file", "out/a.csv")


def test_cloud_identity_is_bucket_and_key_only() -> None:
    s3 = S3Target(type="s3", format="csv", bucket="b", key="k")
    assert target_identity(s3) == ("s3", "b", "k")
    gcs = GCSTarget(type="gcs", format="csv", bucket="b", object="o")
    assert target_identity(gcs) == ("gcs", "b", "o")


def test_a_different_key_is_a_different_destination() -> None:
    a = S3Target(type="s3", format="csv", bucket="b", key="k1")
    b = S3Target(type="s3", format="csv", bucket="b", key="k2")
    assert target_identity(a) != target_identity(b)
