/**
 * @file bgp-minimal-example.cc
 * @brief Minimal BGP example: 3 ASes with transit through AS 65001
 *
 * Demonstrates BGP routing where AS 65001 receives routes from AS 65000
 * and announces them to AS 65002 over a main and a redundant link.
 *
 * Shows:
 *      - network creation
 *      - IP addressing
 *      - BGP speaker setup with eBGP peering
 *      - route propagation over 100 seconds
 *
 * Network flow: 10.0.0.0/25 -> ... -> 10.0.2.0/24
 */

#include "ns3/core-module.h"
#include "ns3/internet-apps-module.h"
#include "ns3/v4ping.h"
#include "bgp-minimal-scenario.h"
#include <cmath>
#include <fstream>
#include <iomanip>
#include <limits>
#include <string>
#include <vector>

using namespace ns3;

#define NS_SIM_LEN Seconds (3600)
#define DEFAULT_LINK_CONFIG_PATH "src/bgp/examples/d12-links.json"
#define RNG_SEED 12345
#define RNG_RUN 1

NS_LOG_COMPONENT_DEFINE ("BgpMinimal");

namespace
{
uint32_t g_rxTotal = 0;
BgpMinimalScenario* g_scenario = nullptr;
std::ofstream g_icmpTrace;

struct IcmpRequestSample
{
    ns3::Time requestTime;
    ns3::Time replyTime;
    ns3::Time rtt;
    std::string activeLink;
    bool received{false};
};

std::vector<IcmpRequestSample> g_icmpSamples;

void
RecordPingRequest ()
{
    IcmpRequestSample sample;
    sample.requestTime = ns3::Simulator::Now ();
    sample.activeLink = g_scenario != nullptr ? g_scenario->GetActiveLinkName () : "unknown";
    g_icmpSamples.push_back (sample);
}

void
OnPingRtt (ns3::Time rtt)
{
    ++g_rxTotal;
    const ns3::Time replyTime = ns3::Simulator::Now ();
    const ns3::Time requestTime = replyTime - rtt;

    std::size_t bestIndex = g_icmpSamples.size ();
    int64_t bestDeltaNs = std::numeric_limits<int64_t>::max ();
    for (std::size_t i = 0; i < g_icmpSamples.size (); ++i)
    {
        if (g_icmpSamples[i].received)
        {
            continue;
        }
        const int64_t deltaNs = std::llabs ((g_icmpSamples[i].requestTime - requestTime).GetNanoSeconds ());
        if (deltaNs < bestDeltaNs)
        {
            bestDeltaNs = deltaNs;
            bestIndex = i;
        }
    }

    if (bestIndex < g_icmpSamples.size () && bestDeltaNs <= ns3::MilliSeconds (500).GetNanoSeconds ())
    {
        g_icmpSamples[bestIndex].received = true;
        g_icmpSamples[bestIndex].replyTime = replyTime;
        g_icmpSamples[bestIndex].rtt = rtt;
    }
}

void
SchedulePingRequestMarkers (ns3::Time windowStart, ns3::Time windowEnd)
{
    for (ns3::Time t = windowStart; t < windowEnd; t += ns3::Seconds (1))
    {
        ns3::Simulator::Schedule (t, &RecordPingRequest);
    }
}

void
WriteIcmpTrace ()
{
    g_icmpTrace << "simulated_time,active_link,RTT,status,request_time,reply_time\n";
    for (std::size_t i = 1; i < g_icmpSamples.size (); ++i)
    {
        const IcmpRequestSample& sample = g_icmpSamples[i];
        g_icmpTrace << std::fixed << std::setprecision (9);
        if (sample.received)
        {
            g_icmpTrace << sample.replyTime.GetSeconds () << ","
                        << sample.activeLink << ","
                        << sample.rtt.GetSeconds () << ","
                        << "received,"
                        << sample.requestTime.GetSeconds () << ","
                        << sample.replyTime.GetSeconds () << "\n";
        }
        else
        {
            g_icmpTrace << sample.requestTime.GetSeconds () << ","
                        << sample.activeLink << ","
                        << ","
                        << "lost,"
                        << sample.requestTime.GetSeconds () << ","
                        << "\n";
        }
    }
}

uint32_t
ExpectedPingReplies (ns3::Time windowStart, ns3::Time windowEnd)
{
    uint32_t expected = 0;
    for (ns3::Time t = ns3::Seconds (10); t < NS_SIM_LEN; t += ns3::Seconds (1))
    {
        if ((t >= windowStart) && (t < windowEnd))
        {
            ++expected;
        }
    }
    return expected;
}
} // namespace

int main (int argc, char *argv[])
{
    std::string linkConfigPath = DEFAULT_LINK_CONFIG_PATH;
    std::string icmpTracePath = "icmp-delay.csv";
    CommandLine cmd;
    cmd.AddValue ("linkConfigPath",
                  "Path to d1-d2 link schedule JSON file",
                  linkConfigPath);
    cmd.AddValue ("icmpTracePath",
                  "CSV output path for ICMP RTT samples",
                  icmpTracePath);
    cmd.Parse (argc, argv);

    // Deterministic simulation settings for repeatable failover experiments.
    RngSeedManager::SetSeed (RNG_SEED);
    RngSeedManager::SetRun (RNG_RUN);

    NS_LOG_INFO ("Setup & Logging");
    LogComponentEnable ("BgpMinimal", LOG_LEVEL_INFO);
    //LogComponentEnable("BgpLog", LOG_LEVEL_INFO); // libbgp
    LogComponentEnable ("Bgp", LOG_LEVEL_INFO); // session

    BgpMinimalScenario scenario;
    g_scenario = &scenario;
    scenario.LoadLinkConfig (linkConfigPath);
    NS_LOG_INFO ("Create nodes for AS routers and internal hosts");
    NS_LOG_INFO ("Create CSMA links (IXP and LANs)");
    scenario.BuildTopology ();
    scenario.ConfigureAddressing ();
    scenario.ConfigureRouting ();
    scenario.ConfigureBgp (NS_SIM_LEN);

    V4PingHelper ping (scenario.GetPingDestinationAddress ());
    ApplicationContainer ping_apps = ping.Install (scenario.GetPingSourceNode ());
    ping_apps.Start (Seconds (10));
    ping_apps.Stop (NS_SIM_LEN);
    Ptr<V4Ping> ping_app = DynamicCast<V4Ping> (ping_apps.Get (0));
    NS_ABORT_MSG_IF (ping_app == nullptr, "Failed to access V4Ping application instance");
    g_icmpTrace.open (icmpTracePath.c_str (), std::ios::out | std::ios::trunc);
    NS_ABORT_MSG_IF (!g_icmpTrace.is_open (), "Failed to open ICMP trace CSV: " << icmpTracePath);
    ping_app->TraceConnectWithoutContext ("Rtt", MakeCallback (&OnPingRtt));
    SchedulePingRequestMarkers (Seconds (10), NS_SIM_LEN);

    scenario.ScheduleConfiguredEvents (NS_SIM_LEN);

    NS_LOG_INFO ("Running simulation...");
    Simulator::Run();

    const uint32_t expectedTotal = ExpectedPingReplies (Seconds (10), NS_SIM_LEN);
    NS_LOG_UNCOND ("[ICMP][SUMMARY] total_rx=" << g_rxTotal
                  << " total_expected=" << expectedTotal
                  << " total_lost=" << (expectedTotal - g_rxTotal));

    NS_LOG_INFO ("Simulation ended. Cleaning up...");
    WriteIcmpTrace ();
    g_icmpTrace.close ();
    g_scenario = nullptr;
    Simulator::Destroy();
    return 0;
}
