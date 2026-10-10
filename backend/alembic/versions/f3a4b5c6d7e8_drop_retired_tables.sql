CREATE TABLE public.action_requests (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    session_id character varying(36) NOT NULL,
    status character varying(32) DEFAULT 'pending'::character varying NOT NULL,
    request_type character varying(50) DEFAULT 'blocker'::character varying NOT NULL,
    prompt text,
    response_content text,
    telegram_chat_id character varying(100),
    telegram_thread_id character varying(100),
    telegram_message_id character varying(100),
    correlation_id character varying(100),
    join_code character varying(32),
    source_client character varying(100),
    metadata jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    resolved_at timestamp with time zone,
    expires_at timestamp with time zone
);
CREATE TABLE public.client_controls (
    id integer NOT NULL,
    client_name character varying(100) NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    disabled_at timestamp with time zone,
    disabled_by character varying(100),
    reason text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE SEQUENCE public.client_controls_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE public.client_controls_id_seq OWNED BY public.client_controls.id;
CREATE TABLE public.persona_scheduled_jobs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    persona_id integer NOT NULL,
    name character varying(200) NOT NULL,
    schedule_type character varying(20) NOT NULL,
    schedule_value character varying(100) NOT NULL,
    schedule_timezone character varying(50) DEFAULT 'UTC'::character varying,
    payload_type character varying(20) DEFAULT 'agent_turn'::character varying,
    payload_message text NOT NULL,
    payload_title character varying(200),
    delivery character varying(20) DEFAULT 'none'::character varying,
    enabled boolean DEFAULT true,
    last_run_at timestamp with time zone,
    next_run_at timestamp with time zone,
    run_count integer DEFAULT 0,
    max_runs integer,
    created_at timestamp with time zone DEFAULT now()
);
CREATE TABLE public.pulse_briefs (
    brief_id text NOT NULL,
    cadence text NOT NULL,
    generated_at timestamp with time zone DEFAULT now() NOT NULL,
    delivered_at timestamp with time zone,
    delivery_target text,
    final_text text,
    agent_run_id text,
    profile_version text,
    status text DEFAULT 'candidate'::text NOT NULL,
    candidate_payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    weak_signals jsonb DEFAULT '{}'::jsonb NOT NULL,
    source_errors jsonb DEFAULT '[]'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.pulse_feedback_events (
    event_id text NOT NULL,
    item_id text,
    brief_id text,
    action text NOT NULL,
    reason text,
    user_ref text,
    event_payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.pulse_improvement_proposals (
    proposal_id text NOT NULL,
    brief_id text,
    title text NOT NULL,
    description text NOT NULL,
    proposed_action jsonb DEFAULT '{}'::jsonb NOT NULL,
    evidence jsonb DEFAULT '{}'::jsonb NOT NULL,
    risk_level text DEFAULT 'low'::text NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    approved_at timestamp with time zone,
    applied_at timestamp with time zone,
    verification_output text
);
CREATE TABLE public.pulse_items (
    item_id text NOT NULL,
    brief_id text,
    title text NOT NULL,
    url text,
    source text,
    published_at timestamp with time zone,
    retrieved_at timestamp with time zone DEFAULT now() NOT NULL,
    topics jsonb DEFAULT '[]'::jsonb NOT NULL,
    item_type text DEFAULT 'factual'::text NOT NULL,
    rank integer,
    score_total numeric,
    score_breakdown jsonb DEFAULT '{}'::jsonb NOT NULL,
    summary_hint text,
    corroboration_status text DEFAULT 'unreviewed'::text NOT NULL,
    attribution jsonb DEFAULT '{}'::jsonb NOT NULL,
    raw_item jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    occurrence_id text NOT NULL
);
CREATE TABLE public.pulse_source_observations (
    observation_id text NOT NULL,
    source text NOT NULL,
    observation_type text NOT NULL,
    evidence_item_ids jsonb DEFAULT '[]'::jsonb NOT NULL,
    agent_note text,
    observation_payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    observed_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.push_subscriptions (
    id character varying(8) NOT NULL,
    endpoint text NOT NULL,
    p256dh_key text NOT NULL,
    auth_key text NOT NULL,
    user_email character varying(255),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    last_used_at timestamp with time zone,
    application_id character varying(100),
    owner_id character varying(100)
);
CREATE TABLE public.webhook_subscriptions (
    id integer NOT NULL,
    url character varying(2048) NOT NULL,
    secret character varying(64) NOT NULL,
    event_types json NOT NULL,
    project_id character varying(100),
    is_active integer NOT NULL,
    description character varying(255),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    failure_count integer NOT NULL
);
CREATE SEQUENCE public.webhook_subscriptions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE public.webhook_subscriptions_id_seq OWNED BY public.webhook_subscriptions.id;
ALTER TABLE ONLY public.client_controls ALTER COLUMN id SET DEFAULT nextval('public.client_controls_id_seq'::regclass);
ALTER TABLE ONLY public.webhook_subscriptions ALTER COLUMN id SET DEFAULT nextval('public.webhook_subscriptions_id_seq'::regclass);
ALTER TABLE ONLY public.client_controls
    ADD CONSTRAINT client_controls_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.action_requests
    ADD CONSTRAINT pk_action_requests PRIMARY KEY (id);
ALTER TABLE ONLY public.persona_scheduled_jobs
    ADD CONSTRAINT pk_persona_scheduled_jobs PRIMARY KEY (id);
ALTER TABLE ONLY public.push_subscriptions
    ADD CONSTRAINT pk_push_subscriptions PRIMARY KEY (id);
ALTER TABLE ONLY public.pulse_briefs
    ADD CONSTRAINT pulse_briefs_pkey PRIMARY KEY (brief_id);
ALTER TABLE ONLY public.pulse_feedback_events
    ADD CONSTRAINT pulse_feedback_events_pkey PRIMARY KEY (event_id);
ALTER TABLE ONLY public.pulse_improvement_proposals
    ADD CONSTRAINT pulse_improvement_proposals_pkey PRIMARY KEY (proposal_id);
ALTER TABLE ONLY public.pulse_items
    ADD CONSTRAINT pulse_items_pkey PRIMARY KEY (occurrence_id);
ALTER TABLE ONLY public.pulse_source_observations
    ADD CONSTRAINT pulse_source_observations_pkey PRIMARY KEY (observation_id);
ALTER TABLE ONLY public.push_subscriptions
    ADD CONSTRAINT uq_push_subscriptions_endpoint UNIQUE (endpoint);
ALTER TABLE ONLY public.webhook_subscriptions
    ADD CONSTRAINT webhook_subscriptions_pkey PRIMARY KEY (id);
CREATE INDEX ix_action_requests_correlation_id ON public.action_requests USING btree (correlation_id);
CREATE INDEX ix_action_requests_join_code ON public.action_requests USING btree (join_code);
CREATE INDEX ix_action_requests_session_id ON public.action_requests USING btree (session_id);
CREATE INDEX ix_action_requests_session_status ON public.action_requests USING btree (session_id, status);
CREATE INDEX ix_action_requests_status ON public.action_requests USING btree (status);
CREATE INDEX ix_action_requests_telegram_chat_id ON public.action_requests USING btree (telegram_chat_id);
CREATE UNIQUE INDEX ix_client_controls_client_name ON public.client_controls USING btree (client_name);
CREATE INDEX ix_persona_scheduled_jobs_next_run ON public.persona_scheduled_jobs USING btree (enabled, next_run_at);
CREATE INDEX ix_push_subscriptions_application_owner ON public.push_subscriptions USING btree (application_id, owner_id);
CREATE INDEX ix_webhook_subscriptions_project ON public.webhook_subscriptions USING btree (project_id);
CREATE INDEX ix_webhook_subscriptions_project_id ON public.webhook_subscriptions USING btree (project_id);
CREATE INDEX pulse_feedback_item_idx ON public.pulse_feedback_events USING btree (item_id, created_at DESC);
CREATE INDEX pulse_items_brief_rank_idx ON public.pulse_items USING btree (brief_id, rank);
CREATE INDEX pulse_items_item_id_idx ON public.pulse_items USING btree (item_id);
CREATE INDEX pulse_items_source_idx ON public.pulse_items USING btree (source);
CREATE INDEX pulse_proposals_status_idx ON public.pulse_improvement_proposals USING btree (status, created_at DESC);
ALTER TABLE ONLY public.action_requests
    ADD CONSTRAINT fk_action_requests_sessions_session_id FOREIGN KEY (session_id) REFERENCES public.sessions(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.persona_scheduled_jobs
    ADD CONSTRAINT fk_persona_scheduled_jobs_persona_persona_id FOREIGN KEY (persona_id) REFERENCES public.persona(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.pulse_items
    ADD CONSTRAINT pulse_items_brief_id_fkey FOREIGN KEY (brief_id) REFERENCES public.pulse_briefs(brief_id) ON DELETE SET NULL;
