#pragma once

#include "bgp-minimal-state.h"
#include "ns3/nstime.h"
#include "ns3/ipv4-address.h"
#include "ns3/node.h"
#include "ns3/ptr.h"

/**
 * @file bgp-minimal-scenario.h
 * @brief Scenario orchestration for the bgp-minimal example.
 *
 * The scenario engine separates:
 * - system/orchestration events (planned link switchover intent), and
 * - physical-world events (link down/up availability changes).
 *
 * This class is introduced as a refactoring boundary to gradually move
 * topology setup and protocol configuration out of main().
 */
class BgpMinimalScenario
{
public:
  enum class LinkId
  {
    MAIN,
    REDUNDANT
  };

  BgpMinimalScenario ();

  // Build nodes, stack, and L2 links.
  void BuildTopology ();

  // Assign inter-router and LAN IPv4 addresses.
  void ConfigureAddressing ();

  // Configure host default routes.
  void ConfigureRouting ();

  // Configure BGP apps, routes, and peering.
  void ConfigureBgp (ns3::Time stopTime);

  // Define and validate switchover lifecycle timing.
  void SetSwitchoverWindow (ns3::Time intentTime,
                            ns3::Time activationTime,
                            ns3::Time hardDeadline);
  bool HasValidSwitchoverWindow () const;

  // System event API: schedule/apply active-link transition intent.
  void ScheduleLinkChange (LinkId currentLink, LinkId newLink, ns3::Time changeTime);
  void ChangeLink (LinkId currentLink, LinkId newLink);

  // Physical-world event handlers: bring primary inter-AS link down/up.
  void BringDownMainLink ();
  void BringUpMainLink ();
  void BringDownRedLink ();
  void BringUpRedLink ();

  // Schedule physical-world primary link failure/recovery events.
  void ScheduleEvents (ns3::Time failTime, ns3::Time repairTime);

  // Accessors for orchestration-level traffic setup.
  ns3::Ptr<ns3::Node> GetPingSourceNode () const;
  ns3::Ipv4Address GetPingDestinationAddress () const;

private:
  bool m_mainPhysicalUp;
  bool m_redPhysicalUp;
  LinkId m_activeLink;

  bool m_hasValidSwitchoverWindow;
  ns3::Time m_switchoverIntentTime;
  ns3::Time m_switchoverActivationTime;
  ns3::Time m_switchoverHardDeadline;

  BgpMinimalState m_state;
};
