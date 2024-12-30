from unittest.mock import MagicMock

import pandas as pd
from langchain_core.embeddings import Embeddings
from langchain_core.outputs.generation import Generation
from langchain_core.outputs.llm_result import LLMResult
from langchain_openai.chat_models.base import ChatOpenAI

from mindsdb.api.executor.data_types.response_type import RESPONSE_TYPE
from mindsdb.integrations.libs.response import HandlerResponse
from mindsdb.integrations.libs.vectordatabase_handler import DistanceFunction, VectorStoreHandler
from mindsdb.integrations.utilities.rag.retrievers.sql_retriever import SQLRetriever
from mindsdb.integrations.utilities.rag.settings import DEFAULT_QUERY_CHECKER_PROMPT_TEMPLATE, DEFAULT_SEMANTIC_PROMPT_TEMPLATE, DEFAULT_SQL_PROMPT_TEMPLATE, LLMExample, ColumnSchema, MetadataSchema, SearchKwargs


class TestSQLRetriever:
    def test_basic(self):
        llm = MagicMock(spec=ChatOpenAI, wraps=ChatOpenAI)
        llm_result = MagicMock(spec=LLMResult, wraps=LLMResult)
        llm_result.generations = [
            [
                Generation(
                    text='''SELECT sd.*, v.*
FROM test_source_table sd
JOIN document_unit du ON sd."Id" = du."DocumentId"
JOIN unit u ON du."UnitKey" = u."UnitKey"
JOIN plant p ON u."PlantKey" = p."PlantKey"
JOIN test_embeddings_table v ON (v."metadata"->>'original_row_id')::int = sd."Id"
WHERE p."PlantName" = 'Beaver Valley'
ORDER BY v.embeddings <->'''
                )
            ]
        ]
        llm.generate_prompt.return_value = llm_result
        vector_db_mock = MagicMock(spec=VectorStoreHandler, wraps=VectorStoreHandler)
        series = pd.Series(
            [0, 'Chunk1', '[1.0, 2.0, 3.0]', {'key1': 'value1'}, 0, 1],
            index=['id', 'content', 'embeddings', 'metadata', 'Id', 'Type']
        )
        df = pd.DataFrame([series])
        vector_db_mock.native_query.return_value = HandlerResponse(
            RESPONSE_TYPE.TABLE,
            data_frame=df
        )
        embeddings_mock = MagicMock(spec=Embeddings, wraps=Embeddings)
        embeddings_mock.embed_query.return_value = list(range(768))

        source_schema = MetadataSchema(
            table='test_source_table',
            description='Contains source documents',
            columns=[
                ColumnSchema(name='Id', type='int', description='Unique ID as primary key of doc'),
                ColumnSchema(name='Type', type='int', description='Document Type', values={1: 'Unknown', 2: 'Site Audit'})
            ]
        )
        unit_schema = MetadataSchema(
            table='unit',
            description='Contains information about specific units of power plants. Several units can be part of a single plant.',
            columns=[
                ColumnSchema(name='UnitKey', type='int', description='Unique ID of the unit'),
                ColumnSchema(name='PlantKey', type='int', description='ID of the plant the unit belongs to')
            ]
        )
        plant_schema = MetadataSchema(
            table='plant',
            description='Contains information about specific power plants',
            columns=[
                ColumnSchema(name='PlantKey', type='int', description='The unique ID of the plant'),
                ColumnSchema(name='PlantName', type='str', description='The name of the plant')
            ]
        )
        document_unit_schema = MetadataSchema(
            table='document_unit',
            description='Links documents to the power plant they are relevant to',
            columns=[
                ColumnSchema(name='DocumentId', type='int', description='The ID of the document associated with the unit'),
                ColumnSchema(name='UnitKey', type='int', description='The ID of the unit the documnet is associated with')
            ]
        )
        all_schemas = [source_schema, unit_schema, plant_schema, document_unit_schema]
        example = LLMExample(
            input='Get me all documents related to the Beaver Valley plant',
            output='''
SELECT sd.*, v.*
FROM test_source_table sd
JOIN document_unit du ON sd."Id" = du."DocumentId"
JOIN unit u ON du."UnitKey" = u."UnitKey"
JOIN plant p ON u."PlantKey" = p."PlantKey"
JOIN test_embeddings_table v ON (v."metadata"->>'original_row_id')::int = sd."Id"
WHERE p."PlantName" = 'Beaver Valley'
ORDER BY v.embeddings <-> '{embeddings}' LIMIT 5;
'''
        )
        sql_retriever = SQLRetriever(
            vector_store_handler=vector_db_mock,
            metadata_schemas=all_schemas,
            examples=[example],
            embeddings_model=embeddings_mock,
            rewrite_prompt_template=DEFAULT_SEMANTIC_PROMPT_TEMPLATE,
            sql_prompt_template=DEFAULT_SQL_PROMPT_TEMPLATE,
            query_checker_template=DEFAULT_QUERY_CHECKER_PROMPT_TEMPLATE,
            embeddings_table='test_embeddings_table',
            source_table='test_source_table',
            distance_function=DistanceFunction.SQUARED_EUCLIDEAN_DISTANCE,
            search_kwargs=SearchKwargs(k=5),
            llm=llm
        )

        docs = sql_retriever.invoke('What are Beaver Valley plant documents for nuclear fuel waste?')
        # Make sure right doc was retrieved.
        assert len(docs) == 1
        assert docs[0].page_content == 'Chunk1'
        assert docs[0].metadata == {'key1': 'value1'}