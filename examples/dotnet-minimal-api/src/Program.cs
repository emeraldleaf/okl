// orders-api: a deliberately small service with the shapes okl's stored lessons bite on.
// Two users, a handful of orders, an in-memory store. Nothing here is production code; it
// exists so an agent can be asked realistic tasks (add an endpoint, add a search) and the
// briefing can be seen doing its job — or not, in the control run.
using OrdersApi;

var builder = WebApplication.CreateBuilder(args);
var app = builder.Build();

app.MapGet("/health", () => Results.Ok(new { ok = true }));

// The caller's own orders only.
app.MapGet("/orders", (HttpContext ctx) =>
{
    var user = Auth.CurrentUser(ctx);
    if (user is null) return Results.Unauthorized();
    return Results.Ok(Store.Orders.Values.Where(o => o.Owner == user));
});

app.Run();

public partial class Program { }
