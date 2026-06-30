#ifndef NS3HELPER_NETWORK_H
#define NS3HELPER_NETWORK_H

#include "ns3/network-module.h"
#include "ns3/internet-module.h"
#include "ns3/ipv4-static-routing-helper.h"

/**
 * @file ns3helper-network.h
 * @brief Small reusable network utilities for the STARS ns-3 examples.
 *
 * The goal is readability and reuse without introducing global state.
 */
namespace ns3helper {

/**
 * @brief Assign /31 IPv4 addresses to a two-endpoint link.
 *
 * @param devices Net devices belonging to the link endpoints.
 * @param addr0 Address for endpoint 0.
 * @param addr1 Address for endpoint 1.
 * @return Interface container for the assigned interfaces.
 */
inline ns3::Ipv4InterfaceContainer
AssignP2p31(const ns3::NetDeviceContainer& devices,
            const ns3::Ipv4Address& addr0,
            const ns3::Ipv4Address& addr1)
{
    ns3::Ipv4InterfaceContainer interfaces;
    ns3::Ipv4Mask mask("255.255.255.254");

    for (uint32_t i = 0; i < devices.GetN(); ++i)
    {
        ns3::Ptr<ns3::NetDevice> device = devices.Get(i);
        ns3::Ptr<ns3::Node> node = device->GetNode();
        ns3::Ptr<ns3::Ipv4> ipv4 = node->GetObject<ns3::Ipv4>();

        int32_t interface = ipv4->GetInterfaceForDevice(device);
        if (interface == -1)
        {
            interface = ipv4->AddInterface(device);
        }

        ns3::Ipv4Address addr = (i == 0) ? addr0 : addr1;
        ipv4->AddAddress(interface, ns3::Ipv4InterfaceAddress(addr, mask));
        ipv4->SetMetric(interface, 1);
        ipv4->SetUp(interface);
        interfaces.Add(ipv4, interface);
    }

    return interfaces;
}

/**
 * @brief Set the IPv4 interface state (up/down) for a link between two nodes.
 *
 * @param nodes Node container that holds both endpoints.
 * @param nodeA Index of endpoint A in @p nodes.
 * @param ifAddrA Interface address for endpoint A.
 * @param nodeB Index of endpoint B in @p nodes.
 * @param ifAddrB Interface address for endpoint B.
 * @param up True to bring both interfaces up, false to bring both down.
 */
inline void
SetLinkStateByInterfaceAddress(const ns3::NodeContainer& nodes,
                               uint32_t nodeA,
                               const ns3::Ipv4Address& ifAddrA,
                               uint32_t nodeB,
                               const ns3::Ipv4Address& ifAddrB,
                               bool up)
{
    ns3::Ptr<ns3::Ipv4> routerA = nodes.Get(nodeA)->GetObject<ns3::Ipv4>();
    ns3::Ptr<ns3::Ipv4> routerB = nodes.Get(nodeB)->GetObject<ns3::Ipv4>();

    uint32_t ifA = routerA->GetInterfaceForAddress(ifAddrA);
    uint32_t ifB = routerB->GetInterfaceForAddress(ifAddrB);

    if (up)
    {
        routerA->SetUp(ifA);
        routerB->SetUp(ifB);
    }
    else
    {
        routerA->SetDown(ifA);
        routerB->SetDown(ifB);
    }
}

/**
 * @brief Bring down a link identified by a two-entry interface container.
 *
 * @param nodes Node container that holds link endpoints.
 * @param iface Interface container for the link (address 0 and 1 as endpoints).
 * @param nodeA Index of endpoint A (default: 1).
 * @param nodeB Index of endpoint B (default: 2).
 */
inline void
bringDownLink(const ns3::NodeContainer& nodes,
              const ns3::Ipv4InterfaceContainer& iface,
              uint32_t nodeA = 1,
              uint32_t nodeB = 2)
{
    SetLinkStateByInterfaceAddress(
        nodes, nodeA, iface.GetAddress(0), nodeB, iface.GetAddress(1), false);
}

/**
 * @brief Bring up a link identified by a two-entry interface container.
 *
 * @param nodes Node container that holds link endpoints.
 * @param iface Interface container for the link (address 0 and 1 as endpoints).
 * @param nodeA Index of endpoint A (default: 1).
 * @param nodeB Index of endpoint B (default: 2).
 */
inline void
bringUpLink(const ns3::NodeContainer& nodes,
            const ns3::Ipv4InterfaceContainer& iface,
            uint32_t nodeA = 1,
            uint32_t nodeB = 2)
{
    SetLinkStateByInterfaceAddress(
        nodes, nodeA, iface.GetAddress(0), nodeB, iface.GetAddress(1), true);
}

/**
 * @brief Configure the default route for a host interface.
 *
 * @param hostIpv4 Host IPv4 stack.
 * @param hostInterfaceAddress Host-side interface address used for egress.
 * @param nextHop Default gateway address.
 * @return Interface index used when installing the default route.
 */
inline uint32_t
SetHostDefaultRoute(const ns3::Ptr<ns3::Ipv4>& hostIpv4,
                    const ns3::Ipv4Address& hostInterfaceAddress,
                    const ns3::Ipv4Address& nextHop)
{
    ns3::Ipv4StaticRoutingHelper staticRouting;
    ns3::Ptr<ns3::Ipv4StaticRouting> hostRt = staticRouting.GetStaticRouting(hostIpv4);
    uint32_t hostIf = hostIpv4->GetInterfaceForAddress(hostInterfaceAddress);
    hostRt->SetDefaultRoute(nextHop, hostIf);
    return hostIf;
}

} // namespace ns3helper

#endif // NS3HELPER_NETWORK_H
