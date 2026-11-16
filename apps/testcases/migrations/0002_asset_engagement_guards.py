from django.db import migrations


SQL = """
CREATE TRIGGER trace_test_asset_insert BEFORE INSERT ON testcases_testcaseasset
WHEN (SELECT engagement_id FROM testcases_testcase WHERE id = NEW.test_case_id)
  != (SELECT engagement_id FROM assets_asset WHERE id = NEW.asset_id)
BEGIN SELECT RAISE(ABORT, 'test asset engagement mismatch'); END;
CREATE TRIGGER trace_test_asset_update BEFORE UPDATE OF test_case_id, asset_id ON testcases_testcaseasset
WHEN (SELECT engagement_id FROM testcases_testcase WHERE id = NEW.test_case_id)
  != (SELECT engagement_id FROM assets_asset WHERE id = NEW.asset_id)
BEGIN SELECT RAISE(ABORT, 'test asset engagement mismatch'); END;
CREATE TRIGGER trace_asset_engagement_update BEFORE UPDATE OF engagement_id ON assets_asset
WHEN EXISTS (SELECT 1 FROM testcases_testcaseasset link JOIN testcases_testcase tc ON tc.id = link.test_case_id
  WHERE link.asset_id = OLD.id AND tc.engagement_id != NEW.engagement_id)
BEGIN SELECT RAISE(ABORT, 'linked asset cannot change engagement'); END;
CREATE TRIGGER trace_test_engagement_update BEFORE UPDATE OF engagement_id ON testcases_testcase
WHEN EXISTS (SELECT 1 FROM testcases_testcaseasset link JOIN assets_asset a ON a.id = link.asset_id
  WHERE link.test_case_id = OLD.id AND a.engagement_id != NEW.engagement_id)
BEGIN SELECT RAISE(ABORT, 'linked test cannot change engagement'); END;
"""


class Migration(migrations.Migration):
    dependencies = [("testcases", "0001_initial")]
    operations = [migrations.RunSQL(SQL, """
        DROP TRIGGER trace_test_asset_insert;
        DROP TRIGGER trace_test_asset_update;
        DROP TRIGGER trace_asset_engagement_update;
        DROP TRIGGER trace_test_engagement_update;
    """)]
