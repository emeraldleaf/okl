using System.Net;
using System.Net.Http.Json;
using Microsoft.AspNetCore.Mvc.Testing;

namespace OrdersApi.Tests;

public class ApiTests : IClassFixture<WebApplicationFactory<Program>>
{
    private readonly HttpClient _client;
    public ApiTests(WebApplicationFactory<Program> factory) => _client = factory.CreateClient();

    [Fact]
    public async Task Health_is_ok()
    {
        var res = await _client.GetAsync("/health");
        Assert.Equal(HttpStatusCode.OK, res.StatusCode);
    }

    [Fact]
    public async Task Listing_orders_is_scoped_to_the_caller()
    {
        _client.DefaultRequestHeaders.Add("X-User-Token", "token-bob");
        var mine = await _client.GetFromJsonAsync<List<Order>>("/orders");
        Assert.Equal(new[] { 3 }, mine!.Select(o => o.Id).ToArray());
    }
}
