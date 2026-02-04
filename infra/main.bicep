// Parameters for flexibility across regions
param location string = resourceGroup().location
param openAiName string = 'openai-${uniqueString(resourceGroup().id)}'
param searchName string = 'search-${uniqueString(resourceGroup().id)}'

// 1. Azure OpenAI Service
resource openAiAccount 'Microsoft.CognitiveServices/accounts@2023-05-01' = {
  name: openAiName
  location: location
  kind: 'OpenAI'
  sku: {
    name: 'S0'
  }
  properties: {
    customSubDomainName: openAiName
    publicNetworkAccess: 'Enabled'
  }
}

// 2. Azure AI Search Service
resource searchService 'Microsoft.Search/searchServices@2023-11-01' = {
  name: searchName
  location: location
  sku: {
    name: 'basic'
  }
  properties: {
    replicaCount: 1
    partitionCount: 1
    hostingMode: 'default'
  }
}

output openAiEndpoint string = openAiAccount.properties.endpoint
output searchEndpoint string = 'https://${searchName}.search.windows.net'