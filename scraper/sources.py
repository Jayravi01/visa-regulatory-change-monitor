"""
Public government and industry source configuration for Module 3
(Visa and Regulatory Change Monitor).

Every page that is collected is registered here, so a source can be added or
retired without changing the collector. docs/SOURCE_REGISTER.md explains why
each source is used. All URLs below are PROPOSED: business approval and a peer
terms-of-use review are still open governance tasks (see the register).

Fields
------
source_id                  Stable identifier used in snapshots, logs and records.
organisation               Publishing organisation.
source_group               government | industry.
source_role                news_listing | policy_page | processing_times | policy_document.
primary_government_source  True only for the government body that makes the rule.
                           Industry summaries need corroboration before publication.
monitors                   Change categories this source is expected to evidence.
"""

SOURCES = [

    # -------------- DEPARTMENT OF HOME AFFAIRS --------------

    {
        "source_id": "homeaffairs_student_500",
        "organisation": "Department of Home Affairs",
        "source_group": "government",
        "source_role": "policy_page",
        "primary_government_source": True,
        "monitors": ["eligibility", "visa_condition", "compliance_requirement", "fee_change"],
        "url": "https://immi.homeaffairs.gov.au/visas/getting-a-visa/visa-listing/student-500"
    },

    {
        "source_id": "homeaffairs_graduate_485",
        "organisation": "Department of Home Affairs",
        "source_group": "government",
        "source_role": "policy_page",
        "primary_government_source": True,
        "monitors": ["eligibility", "visa_condition", "fee_change"],
        "url": "https://immi.homeaffairs.gov.au/visas/getting-a-visa/visa-listing/temporary-graduate-485"
    },

    # Interactive page: most of its content is produced by scripts, so the plain
    # HTTP snapshot may hold little text. The collector flags this with the
    # possible_client_rendered_page warning. It is not worked around.
    {
        "source_id": "homeaffairs_processing_times",
        "organisation": "Department of Home Affairs",
        "source_group": "government",
        "source_role": "processing_times",
        "primary_government_source": True,
        "monitors": ["processing_time"],
        "url": "https://immi.homeaffairs.gov.au/visas/getting-a-visa/visa-processing-times/global-visa-processing-times"
    },

    # The news archive is a landing page whose items are loaded by scripts, so an
    # HTTP snapshot may contain no items. Treated as a registered gap, not hidden.
    {
        "source_id": "homeaffairs_news_archive",
        "organisation": "Department of Home Affairs",
        "source_group": "government",
        "source_role": "news_listing",
        "primary_government_source": True,
        "monitors": ["policy_announcement", "eligibility", "compliance_requirement"],
        "url": "https://immi.homeaffairs.gov.au/news-media/archive"
    },

    # Government fact sheet published as a PDF; the collector extracts its text.
    {
        "source_id": "homeaffairs_student_changes_factsheet",
        "organisation": "Department of Home Affairs",
        "source_group": "government",
        "source_role": "policy_document",
        "primary_government_source": True,
        "monitors": ["eligibility", "compliance_requirement", "fee_change"],
        "url": "https://immi.homeaffairs.gov.au/Visa-subsite/files/changes-to-student-visa-applications-factsheet.pdf"
    },

    # -------------- STUDY AUSTRALIA --------------

    {
        "source_id": "studyaustralia_news",
        "organisation": "Study Australia",
        "source_group": "government",
        "source_role": "news_listing",
        "primary_government_source": True,
        "monitors": ["education_policy", "fee_change", "worker_policy"],
        "url": "https://www.studyaustralia.gov.au/en/tools-and-resources/news"
    },

    # -------------- DEPARTMENT OF EDUCATION --------------

    {
        "source_id": "education_newsroom",
        "organisation": "Department of Education",
        "source_group": "government",
        "source_role": "news_listing",
        "primary_government_source": True,
        "monitors": ["education_policy", "policy_announcement"],
        "url": "https://www.education.gov.au/newsroom"
    },

    {
        "source_id": "education_esos_changes",
        "organisation": "Department of Education",
        "source_group": "government",
        "source_role": "policy_page",
        "primary_government_source": True,
        "monitors": ["education_policy", "compliance_requirement"],
        "url": "https://www.education.gov.au/esos-framework/changes-legislative-framework-overseas-students"
    },

    # -------------- FAIR WORK OMBUDSMAN --------------

    {
        "source_id": "fairwork_news",
        "organisation": "Fair Work Ombudsman",
        "source_group": "government",
        "source_role": "news_listing",
        "primary_government_source": True,
        "monitors": ["worker_policy", "visa_condition"],
        "url": "https://www.fairwork.gov.au/newsroom/news"
    },

    # -------------- MIGRATION INSTITUTE OF AUSTRALIA --------------

    # Industry body, not a rule maker. Records from this source are secondary:
    # they must be corroborated by a government source before publication.
    {
        "source_id": "mia_media_releases",
        "organisation": "Migration Institute of Australia",
        "source_group": "industry",
        "source_role": "news_listing",
        "primary_government_source": False,
        "monitors": ["policy_announcement", "eligibility"],
        "url": "https://mia.org.au/Web/Web/Public-Resources/Media-Releases-Index.aspx"
    },

]
