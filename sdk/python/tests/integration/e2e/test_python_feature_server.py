import json
from datetime import datetime
from typing import List

import pytest
from fastapi.testclient import TestClient

from feast.feast_object import FeastObject
from feast.feature_server import get_app
from tests.integration.feature_repos.integration_test_repo_config import (
    IntegrationTestRepoConfig,
)
from tests.integration.feature_repos.repo_configuration import (
    construct_test_environment,
    construct_universal_feature_views,
    construct_universal_test_data,
)
from tests.integration.feature_repos.universal.entities import (
    customer,
    driver,
    location,
)


@pytest.mark.integration
@pytest.mark.universal_online_stores
def test_get_online_features(python_fs_client):
    request_data_dict = {
        "features": [
            "driver_stats:conv_rate",
            "driver_stats:acc_rate",
            "driver_stats:avg_daily_trips",
        ],
        "entities": {"driver_id": [5001, 5002]},
    }
    response = python_fs_client.post(
        "/get-online-features", data=json.dumps(request_data_dict)
    )

    # Check entities and features are present
    parsed_response = json.loads(response.text)
    assert "metadata" in parsed_response
    metadata = parsed_response["metadata"]
    expected_features = ["driver_id", "conv_rate", "acc_rate", "avg_daily_trips"]
    response_feature_names = metadata["feature_names"]
    assert len(response_feature_names) == len(expected_features)
    for expected_feature in expected_features:
        assert expected_feature in response_feature_names
    assert "results" in parsed_response
    results = parsed_response["results"]
    for result in results:
        # Same order as in metadata
        assert len(result["statuses"]) == 2  # Requested two entities
        for status in result["statuses"]:
            assert status == "PRESENT"
    results_driver_id_index = response_feature_names.index("driver_id")
    assert (
        results[results_driver_id_index]["values"]
        == request_data_dict["entities"]["driver_id"]
    )


@pytest.mark.integration
@pytest.mark.universal_online_stores
def test_push(python_fs_client):
    # TODO(felixwang9817): Note that we choose an entity value of 102 here since it is not included
    # in the existing range of entity values (1-49). This allows us to push data for this test
    # without affecting other tests. This decision is tech debt, and should be resolved by finding a
    # better way to isolate data sources across tests.
    json_data = json.dumps(
        {
            "push_source_name": "location_stats_push_source",
            "df": {
                "location_id": [102],
                "temperature": [4],
                "event_timestamp": [str(datetime.utcnow())],
                "created": [str(datetime.utcnow())],
            },
        }
    )
    response = python_fs_client.post("/push", data=json_data,)

    # Check new pushed temperature is fetched
    assert response.status_code == 200
    assert get_temperatures(python_fs_client, location_ids=[102]) == [4]


def get_temperatures(client, location_ids: List[int]):
    get_request_data = {
        "features": ["pushable_location_stats:temperature"],
        "entities": {"location_id": location_ids},
    }
    response = client.post("/get-online-features", data=json.dumps(get_request_data))
    parsed_response = json.loads(response.text)
    assert "metadata" in parsed_response
    metadata = parsed_response["metadata"]
    response_feature_names = metadata["feature_names"]
    assert "results" in parsed_response
    results = parsed_response["results"]
    results_temperature_index = response_feature_names.index("temperature")
    return results[results_temperature_index]["values"]


@pytest.fixture
def python_fs_client(request):
    config = IntegrationTestRepoConfig()
    environment = construct_test_environment(config, fixture_request=request)
    fs = environment.feature_store
    try:
        entities, datasets, data_sources = construct_universal_test_data(environment)
        feature_views = construct_universal_feature_views(data_sources)
        feast_objects: List[FeastObject] = []
        feast_objects.extend(feature_views.values())
        feast_objects.extend([driver(), customer(), location()])
        fs.apply(feast_objects)
        fs.materialize(environment.start_date, environment.end_date)
        client = TestClient(get_app(fs))
        yield client
    finally:
        fs.teardown()
        environment.data_source_creator.teardown()
