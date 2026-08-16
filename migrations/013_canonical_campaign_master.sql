CREATE UNIQUE INDEX one_master_per_campaign
    ON campaign_memberships(campaign_id)
    WHERE role = 'master';

ALTER TABLE campaigns DROP COLUMN master_user_id;
