"""Public Apache Ranger documents used as the chatbot corpus."""

from __future__ import annotations

# Official project files (Apache License 2.0) and documentation pages.
SOURCES: list[dict[str, str]] = [
    {
        "file": "hdfs-policies.json",
        "kind": "policy",
        "title": "HDFS sample policies",
        "url": "https://raw.githubusercontent.com/apache/ranger/master/hdfs-agent/src/test/resources/hdfs-policies.json",
    },
    {
        "file": "hive-policies.json",
        "kind": "policy",
        "title": "Hive sample policies",
        "url": "https://raw.githubusercontent.com/apache/ranger/master/hive-agent/src/test/resources/hive-policies.json",
    },
    {
        "file": "hbase-policies.json",
        "kind": "policy",
        "title": "HBase sample policies",
        "url": "https://raw.githubusercontent.com/apache/ranger/master/hbase-agent/src/test/resources/hbase-policies.json",
    },
    {
        "file": "knox-policies.json",
        "kind": "policy",
        "title": "Knox sample policies",
        "url": "https://raw.githubusercontent.com/apache/ranger/master/knox-agent/src/test/resources/knox-policies.json",
    },
    {
        "file": "kafka-policies.json",
        "kind": "policy",
        "title": "Kafka sample policies",
        "url": "https://raw.githubusercontent.com/apache/ranger/master/plugin-kafka/src/test/resources/kafka-policies.json",
    },
    {
        "file": "kms-policies.json",
        "kind": "policy",
        "title": "KMS sample policies",
        "url": "https://raw.githubusercontent.com/apache/ranger/master/plugin-kms/src/test/resources/kms-policies.json",
    },
    {
        "file": "policyengine-hive.json",
        "kind": "policy",
        "title": "Hive policy-engine cases",
        "url": "https://raw.githubusercontent.com/apache/ranger/master/agents-common/src/test/resources/policyengine/test_policyengine_hive.json",
    },
    {
        "file": "policyengine-tag-hive.json",
        "kind": "policy",
        "title": "Hive tag-based policy cases",
        "url": "https://raw.githubusercontent.com/apache/ranger/master/agents-common/src/test/resources/policyengine/test_policyengine_tag_hive.json",
    },
    {
        "file": "ranger-readme.md",
        "kind": "markdown",
        "title": "Apache Ranger README",
        "url": "https://raw.githubusercontent.com/apache/ranger/master/README.md",
    },
    {
        "file": "faq.txt",
        "kind": "html",
        "title": "Apache Ranger FAQ",
        "url": "https://ranger.apache.org/faq.html",
    },
    {
        "file": "policy-model.txt",
        "kind": "html",
        "title": "Apache Ranger policy model",
        "url": "https://ranger.apache.org/blogs/policy_model.html",
    },
    {
        "file": "dynamic-expressions.txt",
        "kind": "html",
        "title": "Dynamic expressions in Ranger policies",
        "url": "https://ranger.apache.org/blogs/dynamic_expressions.html",
    },
    {
        "file": "abac.txt",
        "kind": "html",
        "title": "Attribute-based access control in Ranger",
        "url": "https://ranger.apache.org/blogs/adventures_in_abac_1.html",
    },
    {
        "file": "integrating-applications.txt",
        "kind": "html",
        "title": "Integrating applications with Ranger",
        "url": "https://ranger.apache.org/blogs/integrating_applications.html",
    },
    {
        "file": "quick-start.txt",
        "kind": "html",
        "title": "Apache Ranger quick start guide",
        "url": "https://ranger.apache.org/quick_start_guide.html",
    },
]
