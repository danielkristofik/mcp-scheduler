"""Tests for mcp_scheduler.cron_manager – mocked CronTab tests."""

from unittest.mock import MagicMock, patch

from mcp_scheduler import cron_manager


def _mock_job(task_id, enabled=True, slices="0 7 * * *"):
    """Create a mock cron job."""
    job = MagicMock()
    job.comment = f"claude-scheduler:{task_id}"
    job.command = f"mcp-scheduler-run --task-id {task_id}"
    job.is_enabled.return_value = enabled
    job.slices = slices
    job.description.return_value = "Every day at 07:00"
    job.is_valid.return_value = True
    return job


class TestInstallJob:
    @patch.object(cron_manager, "_get_crontab")
    def test_install_creates_job(self, mock_crontab):
        cron = MagicMock()
        job = _mock_job("abc123")
        cron.new.return_value = job
        mock_crontab.return_value = cron

        result = cron_manager.install_job("abc123", "0 7 * * *")

        cron.remove_all.assert_called_once()
        cron.new.assert_called_once()
        job.setall.assert_called_with("0 7 * * *")
        cron.write.assert_called_once()
        assert "Installed" in result


class TestRemoveJob:
    @patch.object(cron_manager, "_get_crontab")
    def test_remove_existing(self, mock_crontab):
        cron = MagicMock()
        cron.remove_all.return_value = 1
        mock_crontab.return_value = cron

        assert cron_manager.remove_job("abc123") is True
        cron.write.assert_called_once()

    @patch.object(cron_manager, "_get_crontab")
    def test_remove_missing(self, mock_crontab):
        cron = MagicMock()
        cron.remove_all.return_value = 0
        mock_crontab.return_value = cron

        assert cron_manager.remove_job("nope") is False


class TestListJobs:
    @patch.object(cron_manager, "_get_crontab")
    def test_list_filters_by_prefix(self, mock_crontab):
        our_job = _mock_job("abc123")
        other_job = MagicMock()
        other_job.comment = "something-else"

        cron = MagicMock()
        cron.__iter__ = MagicMock(return_value=iter([our_job, other_job]))
        mock_crontab.return_value = cron

        jobs = cron_manager.list_jobs()
        assert len(jobs) == 1
        assert jobs[0]["task_id"] == "abc123"


class TestEnableDisable:
    @patch.object(cron_manager, "_get_crontab")
    def test_enable_job(self, mock_crontab):
        job = _mock_job("abc123", enabled=False)
        cron = MagicMock()
        cron.find_comment.return_value = [job]
        mock_crontab.return_value = cron

        assert cron_manager.enable_job("abc123") is True
        job.enable.assert_called_once_with()
        cron.write.assert_called_once()

    @patch.object(cron_manager, "_get_crontab")
    def test_disable_job(self, mock_crontab):
        job = _mock_job("abc123", enabled=True)
        cron = MagicMock()
        cron.find_comment.return_value = [job]
        mock_crontab.return_value = cron

        assert cron_manager.disable_job("abc123") is True
        job.enable.assert_called_once_with(False)
        cron.write.assert_called_once()
