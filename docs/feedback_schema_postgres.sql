CREATE TABLE query_events (
	id SERIAL NOT NULL,
	ts TIMESTAMP WITH TIME ZONE NOT NULL,
	username VARCHAR(80) NOT NULL,
	display_name VARCHAR(120),
	role VARCHAR(20),
	request_id VARCHAR(36) NOT NULL,
	version INTEGER NOT NULL,
	event VARCHAR(20) NOT NULL,
	route VARCHAR(20),
	model VARCHAR(80),
	model_calls INTEGER,
	latency_ms INTEGER,
	status VARCHAR(30),
	vote VARCHAR(10),
	question TEXT,
	sql TEXT,
	explanation TEXT,
	message TEXT,
	hint_text TEXT,
	rows_returned INTEGER,
	langsmith_run_id VARCHAR(36),
	detail TEXT,
	PRIMARY KEY (id)
);

CREATE INDEX ix_query_events_request_id ON query_events (request_id);

CREATE TABLE llm_calls (
	id SERIAL NOT NULL,
	ts TIMESTAMP WITH TIME ZONE NOT NULL,
	username VARCHAR(80),
	role VARCHAR(20),
	request_id VARCHAR(36),
	version INTEGER,
	node VARCHAR(40) NOT NULL,
	model VARCHAR(80),
	system_prompt TEXT,
	user_payload TEXT,
	response_text TEXT,
	error VARCHAR(200),
	latency_ms INTEGER,
	input_tokens INTEGER,
	output_tokens INTEGER,
	langsmith_run_id VARCHAR(36),
	PRIMARY KEY (id)
);

CREATE INDEX ix_llm_calls_request_id ON llm_calls (request_id);
