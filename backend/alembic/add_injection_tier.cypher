// Migration: Add injection_tier field to all Episodic nodes
// Run with: cypher-shell -u neo4j -p $NEO4J_PASSWORD < add_injection_tier.cypher

// Set injection_tier='pending_review' for all episodes without a tier
// This marks them for manual review during the tier unification task
MATCH (e:Episodic)
WHERE e.injection_tier IS NULL
SET e.injection_tier = 'pending_review'
RETURN count(e) AS episodes_updated;

// Create index on injection_tier for efficient filtering
CREATE INDEX episode_injection_tier IF NOT EXISTS
FOR (e:Episodic)
ON (e.injection_tier);
